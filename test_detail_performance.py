"""Detail-only analytics: preserved historical semantics and bounded route work."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import web_app
from demand_features import calculate_detail_region, calculate_features
from market_analysis import load_observations
from nav_database import initialize_database


class DetailRegionTests(unittest.TestCase):
    def test_disclosure_matches_full_features_including_weak_and_ambiguous_ads(self):
        def ad(title="Renholder", description="", counties=("ROGALAND",), **extra):
            return dict(title=title, jobtitle="", description=description,
                        workLocations=[{"county": county} for county in counties],
                        categoryList=[{"categoryType": "STYRK08", "code": "9112", "name": ""}],
                        occupationCategories=[], positioncount=1, current_status="INACTIVE", **extra)

        observations = {
            "complete": ad(counties=("ROGALAND", "Rogaland")),
            "weak": ad(title="Medarbeider", description="Vi trenger en renholder."),
            "ambiguous": ad(counties=("ROGALAND", "OSLO")),
            "missing-location": ad(counties=("ROGALAND", None)),
            "other-region": ad(counties=("OSLO",)),
        }
        official = {"regions": {"11": dict(name="Rogaland", new_vacancies=30,
                    unemployed=60, per_100=50.0, unemployment_rate=2.0)}}
        for query in ("renholder", "zzzznotaprofession"):
            for context in (official, None, {"regions": dict(official["regions"], duplicate=official["regions"]["11"])}):
                with self.subTest(query=query, context=context):
                    rows, _ = calculate_features(observations, query, context)
                    expected = next(row for row in rows if row["fylke"] == "ROGALAND")
                    actual = calculate_detail_region(observations, query, "rogaland", context)
                    self.assertEqual(actual, {key: expected[key] for key in actual})
                    if query == "renholder":
                        self.assertEqual(actual["weak"], 1)
                        self.assertEqual(actual["quality"], 25.0)
        self.assertIsNone(calculate_detail_region(observations, "renholder", "nonexistent"))

    def test_region_history_uses_latest_substantive_version_before_filtering(self):
        with tempfile.TemporaryDirectory(prefix="detail-region-test-") as directory:
            database = Path(directory) / "history.db"
            initialize_database(database)
            with closing(sqlite3.connect(database)) as db, db:
                def version(uid, stamp, county, *, title="Renholder", completeness="complete", published=100,
                            classification=False):
                    db.execute("INSERT OR IGNORE INTO jobs(uuid,status,first_seen_at,last_seen_at) "
                               "VALUES (?,'INACTIVE',0,0)", (uid,))
                    cursor = db.execute("INSERT INTO job_versions(job_uuid,details_modified_at,recorded_at,"
                                        "payload_hash,status,title,positioncount,published,origin,completeness) "
                                        "VALUES (?,?,?,?,'INACTIVE',?,1,?,'feed',?)",
                                        (uid, stamp, stamp, uid + str(stamp), title, published, completeness))
                    version_id = cursor.lastrowid
                    db.execute("INSERT INTO job_locations(version_id,location_no,fylke,fylke_key) VALUES (?,0,?,?)",
                               (version_id, county, county.casefold()))
                    if classification:
                        db.execute("INSERT INTO job_classifications(version_id,category_type,code,name) "
                                   "VALUES (?,'STYRK08','9112','Renholder')", (version_id,))
                    db.execute("UPDATE jobs SET current_version_id=? WHERE uuid=?", (version_id, uid))

                version("moved-out", 1, "ROGALAND")
                version("moved-out", 2, "OSLO")
                version("moved-in", 1, "OSLO")
                version("moved-in", 2, "ROGALAND")
                version("empty-newer", 1, "ROGALAND")
                version("empty-newer", 2, "OSLO", title="")
                version("classified-newer", 1, "ROGALAND")
                version("classified-newer", 2, "OSLO", title="", classification=True)
                version("masked-newer", 1, "ROGALAND")
                version("masked-newer", 2, "OSLO", completeness="masked")
                version("outside-period", 1, "ROGALAND")
                version("outside-period", 2, "OSLO", published=300)
            all_rows, _ = load_observations((0, 200), database)
            regional, metadata = load_observations((0, 200), database, county="rogaland")
            expected = {uid: ad for uid, ad in all_rows.items()
                        if any(loc["county"] == "ROGALAND" for loc in ad["workLocations"])}
            self.assertEqual(regional, expected)
            self.assertEqual(set(regional), {"moved-in", "empty-newer", "masked-newer", "outside-period"})
            self.assertEqual(metadata, {})


class DetailRouteTests(unittest.TestCase):
    uuid = "f5dd5f2e-10f7-4b2c-8674-07654702347a"

    @classmethod
    def setUpClass(cls):
        cls.loaded = web_app.load_detail_job(cls.uuid)
        if cls.loaded[0] is None:
            raise unittest.SkipTest("Reference ACTIVE vacancy is absent from the local snapshot")

    def test_lookup_precedes_regional_work_and_full_features_is_never_called(self):
        order = []
        lookup = web_app.load_detail_job
        region = web_app.detail_region_data

        def load(uid):
            order.append("lookup")
            return lookup(uid)

        def data(query, county):
            order.append("region")
            return region(query, county)

        with patch("web_app.features", side_effect=AssertionError("Full features on detail")), \
                patch("web_app.load_detail_job", side_effect=load), \
                patch("web_app.detail_region_data", side_effect=data):
            page = web_app.render("Renholder", "Rogaland", self.uuid)
        self.assertEqual(order, ["lookup", "region"])
        self.assertIn(web_app.e(self.loaded[0]["title"]), page)
        self.assertIn(web_app.e(self.loaded[0]["employer_name"]), page)
        self.assertIn('id="datagrunnlag"', page)
        self.assertIn('class="explore-job-section detail-application-main"', page)
        self.assertIn("Flere relevante stillinger", page)
        # Contact/application and the complete vacancy markup remain unchanged.
        self.assertIn(web_app.job_detail("Renholder", "ROGALAND", self.uuid, loaded=self.loaded), page)

    def test_live_county_fields_match_full_features(self):
        # Keep this regression check's reference cache outside the project.
        with tempfile.TemporaryDirectory(prefix="detail-feature-reference-") as directory, \
                patch("web_app.CACHE_DIR", Path(directory)):
            rows, _ = web_app.features("renholder")
        for county in ("Rogaland", "Oslo", "Vestland"):
            with self.subTest(county=county):
                actual = web_app.detail_region_data("Renholder", county)
                expected = next(row for row in rows if row["fylke"].casefold() == county.casefold())
                self.assertEqual(actual, {key: expected[key] for key in actual})
                self.assertEqual(web_app.data_details([actual]), web_app.data_details([expected]))

    def test_missing_and_inactive_jobs_skip_analytics_and_related_matching(self):
        with closing(sqlite3.connect(web_app.DATABASE.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            inactive = db.execute("SELECT uuid FROM jobs WHERE status='INACTIVE' LIMIT 1").fetchone()
        for uid in ("missing-vacancy", inactive[0] if inactive else "also-missing"):
            with self.subTest(uid=uid), \
                    patch("web_app.features", side_effect=AssertionError("Full features on unavailable ad")), \
                    patch("web_app.detail_region_data", side_effect=AssertionError("Analytics on unavailable ad")), \
                    patch("web_app.active_matches", side_effect=AssertionError("Matching on unavailable ad")):
                page = web_app.render("Renholder", "Rogaland", uid)
            self.assertIn("Annonsen er ikke tilgjengelig", page)
            self.assertIn('id="datagrunnlag"', page)

    def test_invalid_region_and_case_insensitive_canonical_region(self):
        with patch("web_app.features", side_effect=AssertionError("Full features for region validation")):
            for county in ("Rogaland", "ROGALAND", "rogaland"):
                row = web_app.detail_region_data("Renholder", county)
                self.assertEqual(row["fylke"], "ROGALAND")
            with patch("web_app.active_matches", side_effect=AssertionError("Matching for invalid region")):
                page = web_app.render("Renholder", "nonexistent-region", self.uuid)
            self.assertIn("Fylket finnes ikke i dette utvalget", page)
            self.assertNotIn(web_app.e(self.loaded[0]["title"]), page)

    def test_region_cache_is_invalidated_by_data_source_version(self):
        web_app.cached_detail_region.cache_clear()
        with patch("web_app.feature_source_version", side_effect=[("a",), ("a",), ("b",)]), \
                patch("web_app.period_bounds", return_value=(0, 200)), \
                patch("web_app.load_observations", return_value=({}, {})) as read:
            for _ in range(3):
                web_app.detail_region_data("Renholder", "Rogaland")
        self.assertEqual(read.call_count, 2)
        web_app.cached_detail_region.cache_clear()


if __name__ == "__main__":
    unittest.main()
