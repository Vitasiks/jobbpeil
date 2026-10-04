"""Deterministic Vakt fallback selection tests using temporary SQLite only."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import web_app
from nav_database import initialize_database, utc_microseconds


class VaktFallbackTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="vakt-fallback-test-")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "vakt.db"
        initialize_database(self.database)
        self.subscription_id = 17
        self.profession = "Lagermedarbeider, jobbe med hunder hundefrisør assistent"
        self.activation = utc_microseconds("2026-09-29T12:00:00+00:00")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO vakt_subscriptions "
                "(id,email,profession_query,profession_query_key,fylke,active,created_at,"
                "verified_at,verification_token,unsubscribe_token) "
                "VALUES (?,?,?,?,?,1,?,?,?,?)",
                (self.subscription_id, "fixture@example.invalid", self.profession,
                 web_app.vakt_text_key(self.profession), "Vestfold", "test",
                 "2026-09-29T12:00:00+00:00", "fixture-verification-token-00000000000000000000",
                 "fixture-unsubscribe-token-00000000000000000000"),
            )
        self.jobs = {}
        self.dates = {}
        self.strict_matches = {}
        self.strict_patch = patch(
            "web_app.active_matches",
            side_effect=lambda *_args: (self.strict_matches, self.dates),
        )
        self.strict_patch.start()
        self.addCleanup(self.strict_patch.stop)
        self.version_patch = patch("web_app.active_jobs_source_version", return_value="fallback-test")
        self.version_patch.start()
        self.addCleanup(self.version_patch.stop)
        self.jobs_loader = Mock(side_effect=lambda _version: self.jobs)
        self.jobs_patch = patch("web_app.cached_active_jobs", self.jobs_loader)
        self.jobs_patch.start()
        self.addCleanup(self.jobs_patch.stop)
        self.dates_patch = patch("web_app.cached_active_published_dates", side_effect=lambda _version: self.dates)
        self.dates_patch.start()
        self.addCleanup(self.dates_patch.stop)

    def add_job(self, uuid, title, *, county="Vestfold", description="", category=None, day=30):
        locations = [{"county": county, "municipal": county + " kommune"}]
        ad = {"uuid": uuid, "status": "ACTIVE", "title": title,
              "description": description, "workLocations": locations,
              "employer": {"name": "Fixture employer"},
              "occupationCategories": [], "categoryList": []}
        if category:
            ad["occupationCategories"] = [{"level1": category, "level2": ""}]
        self.jobs[uuid] = ad
        self.dates[uuid] = utc_microseconds(f"2026-09-{day:02d}T13:00:00+00:00")
        return ad, locations, {"title": 12}, 12

    def candidates(self, limit=10):
        return web_app.get_vakt_candidates({"id": self.subscription_id}, limit=limit,
                                           database=self.database)

    def sent_count(self):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute("SELECT COUNT(*) FROM vakt_sent_jobs").fetchone()[0]

    def test_fallback_terms_keep_norwegian_and_remove_stopwords(self):
        self.assertEqual(web_app.normalize_vakt_fallback_terms(self.profession),
                         ("lagermedarbeider", "hunder", "hundefrisør", "assistent"))
        self.assertEqual(web_app.normalize_vakt_fallback_terms("  Sjåfør / fører; på jobb—Oslo "),
                         ("sjåfør", "fører", "oslo"))

    def test_contiguous_title_phrase_does_not_cross_title_fields(self):
        terms = ("lagermedarbeider", "hunder")
        ad = {"title": "Lagermedarbeider", "jobtitle": "hunder"}
        score, reasons = web_app._vakt_fallback_relevance(ad, terms)
        self.assertEqual(score, 75)
        self.assertIn("title:lagermedarbeider", reasons)
        self.assertIn("title:hunder", reasons)

    def test_strict_kokk_candidate_remains_absolute_priority(self):
        self.profession = "Kokk"
        self._set_profession("Kokk")
        strict = self.add_job("strict-kokk", "Kokk")
        self.strict_matches = {"strict-kokk": strict}
        self.add_job("fallback-kokk", "Kokkemedarbeider hunder")
        result = self.candidates()
        self.assertEqual([item["vacancy_uuid"] for item in result], ["strict-kokk"])
        self.jobs_loader.assert_not_called()

    def _set_profession(self, profession):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE vakt_subscriptions SET profession_query=? WHERE id=?",
                               (profession, self.subscription_id))

    def test_fallback_runs_only_after_strict_result_is_empty(self):
        self.add_job("fallback-one", "Lagermedarbeider")
        self.strict_matches = {"strict": self.add_job("strict", "Renholder")}
        self.candidates()
        self.jobs_loader.assert_not_called()

    def test_fallback_stays_in_selected_county(self):
        self.add_job("vestfold", "Lagermedarbeider")
        self.add_job("oslo", "Lagermedarbeider", county="Oslo")
        result = self.candidates()
        self.assertEqual([item["vacancy_uuid"] for item in result], ["vestfold"])
        self.assertTrue(all(item["fylke"] == "Vestfold" for item in result))

    def test_title_and_multiple_title_terms_rank_above_weak_matches(self):
        self.add_job("description-one", "Uten tittel", description="Vi trenger hunder.")
        self.add_job("description-two", "Uten tittel", description="Hunder og hundefrisør søkes.")
        self.add_job("category", "Medarbeider", category="Lagermedarbeider")
        self.add_job("title-one", "Lagermedarbeider")
        self.add_job("title-multiple", "Lagermedarbeider hundefrisør")
        result = self.candidates()
        ids = [item["vacancy_uuid"] for item in result]
        self.assertEqual(ids[0], "title-multiple")
        self.assertLess(ids.index("title-multiple"), ids.index("title-one"))
        self.assertLess(ids.index("title-one"), ids.index("category"))
        self.assertLess(ids.index("category"), ids.index("description-two"))
        self.assertNotIn("description-one", ids)
        self.assertTrue(any("title:lagermedarbeider" in item["relevance"]["reasons"]
                            for item in result))
        self.assertTrue(any("category:lagermedarbeider" in item["relevance"]["reasons"]
                            for item in result))
        self.assertTrue(any("description:hunder" in item["relevance"]["reasons"]
                            for item in result))

    def test_multiple_title_terms_beat_one_weak_title_match(self):
        self.add_job("generic-title-term", "Assistent")
        self.add_job("two-title-terms", "Lagermedarbeider hundefrisør")
        result = self.candidates()
        self.assertEqual(result[0]["vacancy_uuid"], "two-title-terms")
        self.assertEqual([item["vacancy_uuid"] for item in result], ["two-title-terms"])
        self.assertGreater(result[0]["relevance"]["score"], 0)

    def test_fresher_vacancy_wins_equal_relevance_tie(self):
        self.add_job("older", "Lagermedarbeider", day=29)
        self.add_job("newer", "Lagermedarbeider", day=30)
        result = self.candidates()
        self.assertEqual([item["vacancy_uuid"] for item in result], ["newer", "older"])

    def test_fallback_is_limited_to_four_and_preview_does_not_mark_sent(self):
        for index in range(6):
            self.add_job(f"title-{index}", f"Lagermedarbeider hundefrisør {index}")
        result = self.candidates(limit=10)
        self.assertEqual(len(result), 4)
        self.assertEqual(self.sent_count(), 0)

    def test_inactive_and_pending_subscriptions_do_not_run_fallback(self):
        self.add_job("candidate", "Lagermedarbeider")
        for active, verified in ((0, "2026-09-29T12:00:00+00:00"), (1, None)):
            with closing(sqlite3.connect(self.database)) as connection, connection:
                connection.execute("UPDATE vakt_subscriptions SET active=?,verified_at=? WHERE id=?",
                                   (active, verified, self.subscription_id))
            self.jobs_loader.reset_mock()
            self.assertEqual(self.candidates(), [])
            self.jobs_loader.assert_not_called()