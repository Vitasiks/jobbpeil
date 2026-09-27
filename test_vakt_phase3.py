"""Controlled, local checks for the Phase 3 Vakt candidate layer."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nav_database import initialize_database, utc_microseconds
from web_app import get_vakt_candidates, mark_vakt_jobs_sent


def ad(uuid, title, county, status="ACTIVE"):
    return {
        "uuid": uuid, "status": status, "title": title, "jobtitle": title,
        "employer": {"name": "Test employer"},
        "workLocations": [{"county": county, "municipal": "Test kommune"}],
    }


class VaktPhase3Tests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "vakt-test.db"
        initialize_database(self.database)
        self.subscription_ids = {}
        db = sqlite3.connect(self.database)
        try:
            for label, active, verified_at, county in (
                ("active", 1, "2026-09-21T12:00:00+00:00", "Oslo"),
                ("pending", 0, None, "Oslo"),
                ("inactive", 0, "2026-09-21T12:00:00+00:00", "Oslo"),
                ("other", 1, "2026-09-21T12:00:00+00:00", "Oslo"),
            ):
                cursor = db.execute(
                    "INSERT INTO vakt_subscriptions "
                    "(email, profession_query, profession_query_key, fylke, active, created_at, "
                    "verified_at, verification_token, unsubscribe_token) "
                    "VALUES (?, 'nurse', 'nurse', ?, ?, '2026-09-21T12:00:00+00:00', ?, ?, ?)",
                    (label + "@example.test", county, active, verified_at, label + "-verify", label + "-unsubscribe"),
                )
                self.subscription_ids[label] = cursor.lastrowid
            db.commit()
        finally:
            db.close()

        self.matches = {
            "A": (ad("A", "Nurse A", "Oslo"), ad("A", "Nurse A", "Oslo")["workLocations"], {"title": 12}, 12),
            "B": (ad("B", "Nurse B", "Oslo"), ad("B", "Nurse B", "Oslo")["workLocations"], {"title": 10}, 10),
            "E": (ad("E", "Nurse E", "Oslo"), ad("E", "Nurse E", "Oslo")["workLocations"], {"title": 9}, 9),
            "C": (ad("C", "Nurse C", "Agder"), ad("C", "Nurse C", "Agder")["workLocations"], {"title": 20}, 20),
            "D": (ad("D", "Nurse D", "Oslo", "INACTIVE"), ad("D", "Nurse D", "Oslo")["workLocations"], {"title": 15}, 15),
        }
        activation = utc_microseconds("2026-09-21T12:00:00+00:00")
        self.dates = {uuid: activation + offset for offset, uuid in enumerate("ABCD")}

    def tearDown(self):
        self.tempdir.cleanup()

    def candidates(self, subscription_id, limit=4, expect_matching=True):
        with patch("web_app.active_matches", return_value=(self.matches, self.dates)) as matching:
            result = get_vakt_candidates({"id": subscription_id}, limit=limit, database=self.database)
        if expect_matching:
            self.assertEqual(matching.call_args.args, ("nurse", "Oslo"))
        else:
            matching.assert_not_called()
        return result

    def test_eligibility_region_ranking_and_preview(self):
        before = self.sent_count()
        candidates = self.candidates(self.subscription_ids["active"])
        self.assertEqual([item["vacancy_uuid"] for item in candidates], ["A", "B"])
        self.assertNotIn("E", [item["vacancy_uuid"] for item in candidates])
        self.assertTrue(all(item["fylke"] == "Oslo" for item in candidates))
        self.assertTrue(all("job=" + item["vacancy_uuid"] in item["detail_url"] for item in candidates))
        self.assertEqual(len(self.candidates(self.subscription_ids["active"], limit=1)), 1)
        self.assertEqual(self.sent_count(), before, "preview must never mark sent jobs")
        self.assertEqual(self.candidates(self.subscription_ids["pending"], expect_matching=False), [])
        self.assertEqual(self.candidates(self.subscription_ids["inactive"], expect_matching=False), [])

    def test_per_subscription_deduplication(self):
        self.assertEqual(mark_vakt_jobs_sent(self.subscription_ids["active"], ["A"], database=self.database), 1)
        self.assertEqual(mark_vakt_jobs_sent(self.subscription_ids["active"], ["A"], database=self.database), 0)
        self.assertEqual([item["vacancy_uuid"] for item in self.candidates(self.subscription_ids["active"])], ["B"])
        self.assertEqual([item["vacancy_uuid"] for item in self.candidates(self.subscription_ids["other"])], ["A", "B"])

    def sent_count(self):
        db = sqlite3.connect(self.database)
        try:
            return db.execute("SELECT count(*) FROM vakt_sent_jobs").fetchone()[0]
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
