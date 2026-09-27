"""Activation-time eligibility on temporary SQLite, never real SMTP."""
from contextlib import closing, redirect_stdout
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nav_database import initialize_database, utc_microseconds
import web_app
import vakt_run_all
import vakt_run_once


class VaktActivationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="vakt-activation-test-")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "vakt.db"
        initialize_database(self.database)
        self.activation = utc_microseconds("2026-09-24T09:50:00+00:00")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO vakt_subscriptions "
                "(id,email,profession_query,profession_query_key,fylke,active,"
                "created_at,verified_at,verification_token,unsubscribe_token,last_checked_at) "
                "VALUES (1,'test@example.test','nurse','nurse','Oslo',1,"
                "'2026-09-20T00:00:00+00:00','2026-09-24T09:50:00+00:00',"
                "'verify-test','unsubscribe-test','2026-09-25T12:00:00+00:00')"
            )
        self.matches = {}
        self.dates = {}
        matching_patch = patch("web_app.active_matches", side_effect=lambda *args: (self.matches, self.dates))
        self.matching = matching_patch.start()
        self.addCleanup(matching_patch.stop)
        smtp_patch = patch("web_app.smtplib.SMTP", side_effect=AssertionError("SMTP forbidden"))
        self.smtp = smtp_patch.start()
        self.addCleanup(smtp_patch.stop)

    def add(self, uuid, published):
        locations = [{"county": "Oslo", "municipal": "Oslo"}]
        ad = {"status": "ACTIVE", "title": "Nurse " + uuid, "employer": {"name": "Test"}}
        self.matches[uuid] = (ad, locations, {"title": 12}, 12)
        self.dates[uuid] = published

    def candidates(self):
        return web_app.get_vakt_candidates({"id": 1}, database=self.database)

    def ids(self):
        return [candidate["vacancy_uuid"] for candidate in self.candidates()]

    def test_old_vacancy_excluded_despite_recent_update_or_earlier_creation(self):
        self.add("yesterday", utc_microseconds("2026-09-23T12:00:00+00:00"))
        self.add("one_microsecond_before", self.activation - 1)
        self.matches["yesterday"][0]["updated"] = "2026-09-25T12:00:00+00:00"
        self.assertEqual(self.ids(), [])

    def test_exact_boundary_and_after_activation(self):
        self.add("equal", self.activation)
        self.add("after", self.activation + 1)
        self.assertEqual(self.ids(), ["equal", "after"])

    def test_dedupe_new_vacancy_already_sent(self):
        self.add("sent", self.activation + 1)
        self.add("unsent", self.activation + 2)
        web_app.mark_vakt_jobs_sent(1, ["sent"], database=self.database)
        self.assertEqual(self.ids(), ["unsent"])

    def test_late_ingestion_not_excluded_by_last_checked(self):
        self.assertEqual(self.ids(), [])
        # It appears only on the next catalogue read, but was published before
        # last_checked_at and after activation. No date-based cursor may lose it.
        self.add("arrived_late", self.activation + 60_000_000)
        self.assertEqual(self.ids(), ["arrived_late"])
        self.assertEqual(self.ids(), ["arrived_late"])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM vakt_sent_jobs").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT last_checked_at FROM vakt_subscriptions").fetchone()[0],
                             "2026-09-25T12:00:00+00:00")

    def test_invalid_missing_publication_excluded(self):
        for number, value in enumerate((None, "invalid", "2026-09-25", "999999999999999999",
                                        True, float('nan'), float('inf'), 10**30)):
            self.add(str(number), value)
        self.add("no-date-entry", None)
        del self.dates["no-date-entry"]
        self.add("valid", self.activation + 1)
        self.assertEqual(self.ids(), ["valid"])

    def test_limit_four_after_time_filter_preserves_order(self):
        self.add("old", self.activation - 1)
        self.add("missing", None)
        for index in range(7):
            self.add(f"new-{index}", self.activation + index)
        self.assertEqual(self.ids(), ["new-0", "new-1", "new-2", "new-3"])

    def test_timezone_offset_and_microsecond_precision(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE vakt_subscriptions SET verified_at=?",
                               ("2026-09-24T11:50:00.000001+02:00",))
        self.add("before", self.activation)
        self.add("equal", self.activation + 1)
        self.assertEqual(self.ids(), ["equal"])

    def test_invalid_or_naive_activation_never_assumes_timezone(self):
        self.add("new", self.activation + 1)
        for value in (None, "", "broken", "2026-09-24T09:50:00", "2026-09-24"):
            with self.subTest(value=value):
                with closing(sqlite3.connect(self.database)) as connection, connection:
                    connection.execute("UPDATE vakt_subscriptions SET verified_at=?", (value,))
                self.matching.reset_mock()
                self.assertEqual(self.ids(), [])
                self.matching.assert_not_called()

    def check_runner(self, module, dry_args, send_args):
        self.add("old", self.activation - 1)
        self.add("new", self.activation + 1)
        with patch.object(module, "DATABASE", self.database), \
                patch.object(module, "send_vakt_job_alert_email", return_value=True) as send, \
                patch.object(module, "mark_vakt_jobs_sent", wraps=web_app.mark_vakt_jobs_sent) as mark, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(dry_args), 0)
            send.assert_not_called()
            mark.assert_not_called()
            self.assertEqual(module.main(send_args), 0)
            send.assert_called_once()
            self.assertEqual([item["vacancy_uuid"] for item in send.call_args.args[1]], ["new"])
            mark.assert_called_once_with(1, ["new"], database=self.database)
        self.smtp.assert_not_called()
        self.assertEqual(self.ids(), [])

    def test_one_shot_uses_shared_filter_in_dry_and_send_modes(self):
        self.check_runner(vakt_run_once, ["--subscription-id", "1", "--dry-run"],
                          ["--subscription-id", "1"])

    def test_batch_uses_shared_filter_in_dry_and_send_modes(self):
        self.check_runner(vakt_run_all, ["--dry-run"], [])


if __name__ == "__main__":
    unittest.main()
