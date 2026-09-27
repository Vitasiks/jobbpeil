"""Batch checks with temporary databases and mocked email/matching helpers."""
from contextlib import closing, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from nav_database import initialize_database
import vakt_run_all as batch


class VaktBatchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="vakt-batch-test-")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "source.db"
        initialize_database(self.database)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            for sid, active, verified in ((1, 1, "confirmed"), (2, 0, "confirmed"),
                                          (3, 1, None), (4, 0, None), (5, 1, "confirmed")):
                connection.execute(
                    "INSERT INTO vakt_subscriptions "
                    "(id,email,profession_query,profession_query_key,fylke,active,"
                    "created_at,verified_at,verification_token,unsubscribe_token) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (sid, f"reader{sid}@example.test", f"Profession {sid}",
                     f"profession {sid}", "Oslo", active, "created", verified,
                     f"secret-verify-{sid}", f"secret-unsubscribe-{sid}"),
                )
        self.start_patch("vakt_run_all.DATABASE", self.database)
        self.smtp = self.start_patch("web_app.smtplib.SMTP",
                                     side_effect=AssertionError("SMTP forbidden"))
        self.match = self.start_patch("vakt_run_all.get_vakt_candidates", return_value=[])
        self.send = self.start_patch("vakt_run_all.send_vakt_job_alert_email", return_value=True)
        self.mark = self.start_patch("vakt_run_all.mark_vakt_jobs_sent", return_value=1)

    def start_patch(self, target, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def invoke(self, arguments=None):
        output = io.StringIO()
        with redirect_stdout(output):
            status = batch.main(arguments or [])
        self.smtp.assert_not_called()
        text = output.getvalue()
        self.assertNotIn("secret-", text)
        self.assertNotIn("Traceback", text)
        rows = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
        return status, text, rows

    @staticmethod
    def candidates(subscription, **kwargs):
        return [{"vacancy_uuid": f"job-{subscription['id']}", "title": "Test vacancy",
                 "employer": "Test employer", "fylke": "Oslo"}]

    def test_active_verified_filter_and_no_candidates(self):
        status, text, rows = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual([row["id"] for row in rows], [1, 5])
        self.assertEqual([row["status"] for row in rows], ["NO_NEW", "NO_NEW"])
        self.assertEqual(self.match.call_count, 2)
        for call in self.match.call_args_list:
            subscription = call.args[0]
            self.assertEqual(subscription["active"], 1)
            self.assertIsNotNone(subscription["verified_at"])
            self.assertTrue(set(("id", "email", "profession_query", "profession_query_key",
                                 "fylke", "active", "verified_at", "unsubscribe_token"))
                            .issubset(subscription))
            self.assertEqual(call.kwargs, {"limit": 4, "database": self.database})
        self.send.assert_not_called()
        self.mark.assert_not_called()
        self.assertIn("Subscriptions checked: 2", text)
        self.assertIn("No new jobs: 2", text)
        self.assertIn("Emails sent: 0", text)

    def test_successful_send_today_skips_second_batch(self):
        self.match.side_effect = self.candidates
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO vakt_sent_jobs (subscription_id, vacancy_uuid, sent_at) "
                "VALUES (1, 'previous', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
        status, text, rows = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual([row["status"] for row in rows],
                         ["SKIP_ALREADY_SENT_TODAY", "SENT"])
        self.send.assert_called_once()
        self.mark.assert_called_once_with(5, ["job-5"], database=self.database)
        self.assertIn("Emails sent: 1", text)

    def test_sent_yesterday_allows_today(self):
        self.match.side_effect = self.candidates
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO vakt_sent_jobs (subscription_id, vacancy_uuid, sent_at) "
                "VALUES (1, 'previous', '2026-09-24T10:00:00+00:00')"
            )
        status, _, rows = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual([row["status"] for row in rows], ["SENT", "SENT"])

    def test_multiple_rows_with_same_timestamp_are_one_daily_send(self):
        self.match.side_effect = self.candidates
        timestamp = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executemany(
                "INSERT INTO vakt_sent_jobs (subscription_id, vacancy_uuid, sent_at) "
                "VALUES (1, ?, ?)",
                [("previous-a", timestamp), ("previous-b", timestamp)],
            )
        status, _, rows = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual([row["status"] for row in rows],
                         ["SKIP_ALREADY_SENT_TODAY", "SENT"])
        self.send.assert_called_once()

    def test_oslo_timezone_and_dst(self):
        from vakt_daily import alert_sent_today
        cases = (
            ("2026-01-15T21:30:00+00:00", "2026-01-15T23:30:00+01:00"),
            ("2026-07-15T21:30:00+00:00", "2026-07-15T23:30:00+02:00"),
        )
        for sent_at, now in cases:
            with self.subTest(sent_at=sent_at):
                with closing(sqlite3.connect(self.database)) as connection, connection:
                    connection.execute("DELETE FROM vakt_sent_jobs")
                    connection.execute(
                        "INSERT INTO vakt_sent_jobs (subscription_id, vacancy_uuid, sent_at) "
                        "VALUES (1, 'previous', ?)", (sent_at,))
                self.assertTrue(alert_sent_today(
                    1, self.database, datetime.fromisoformat(now)))

    def test_success_send_then_mark(self):
        self.match.side_effect = self.candidates
        sequence = Mock()
        sequence.attach_mock(self.match, "matching")
        sequence.attach_mock(self.send, "send")
        sequence.attach_mock(self.mark, "mark")
        status, text, rows = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual([row["status"] for row in rows], ["SENT", "SENT"])
        self.assertEqual([call[0] for call in sequence.mock_calls],
                         ["matching", "send", "mark", "matching", "send", "mark"])
        self.assertEqual(self.mark.call_args_list[0].args, (1, ["job-1"]))
        self.assertEqual(self.mark.call_args_list[1].args, (5, ["job-5"]))
        for call in self.mark.call_args_list:
            self.assertEqual(call.kwargs, {"database": self.database})
        self.assertIn("Emails sent: 2", text)
        self.assertIn("Errors: 0", text)

    def test_smtp_failure_no_mark_and_continue(self):
        self.match.side_effect = self.candidates
        self.send.side_effect = [RuntimeError("secret-smtp-password"), True]
        status, text, rows = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual([row["status"] for row in rows], ["ERROR", "SENT"])
        self.assertEqual(self.send.call_count, 2)
        self.mark.assert_called_once_with(5, ["job-5"], database=self.database)
        self.assertIn("Emails sent: 1", text)
        self.assertIn("Errors: 1", text)

    def test_false_result_no_mark_and_continue(self):
        self.match.side_effect = self.candidates
        self.send.side_effect = [False, True]
        status, _, rows = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual([row["status"] for row in rows], ["ERROR", "SENT"])
        self.mark.assert_called_once_with(5, ["job-5"], database=self.database)

    def test_matching_error_continues(self):
        self.match.side_effect = [ValueError("secret-in-error"), [{"vacancy_uuid": "job-5"}]]
        status, _, rows = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual([row["status"] for row in rows], ["ERROR", "SENT"])
        self.send.assert_called_once()
        self.mark.assert_called_once_with(5, ["job-5"], database=self.database)

    def test_malformed_candidates_continue_before_smtp(self):
        for invalid in ([{}], [{"vacancy_uuid": ""}], None,
                        [{"vacancy_uuid": str(i)} for i in range(5)]):
            with self.subTest(invalid=invalid):
                self.match.side_effect = [invalid, [{"vacancy_uuid": "job-5"}]]
                self.send.reset_mock()
                self.mark.reset_mock()
                status, _, rows = self.invoke()
                self.assertEqual(status, 1)
                self.assertEqual([row["status"] for row in rows], ["ERROR", "SENT"])
                self.send.assert_called_once()
                self.mark.assert_called_once_with(5, ["job-5"], database=self.database)

    def test_mark_failure_reports_sent_and_continues(self):
        self.match.side_effect = self.candidates
        self.mark.side_effect = [sqlite3.OperationalError("secret-db-error"), 1]
        status, text, rows = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual([row["status"] for row in rows], ["ERROR", "SENT"])
        self.assertIn("Email sent", rows[0]["warning"])
        self.assertIn("Emails sent: 2", text)
        self.assertEqual(self.send.call_count, 2)

    def test_dry_run_no_smtp_no_mark_and_no_source_writes(self):
        before = hashlib.sha256(self.database.read_bytes()).digest()
        snapshots = []

        def preview(subscription, limit, database):
            self.assertEqual(limit, 4)
            self.assertNotEqual(database, self.database)
            snapshots.append(database)
            initialize_database(database)
            return self.candidates(subscription)

        self.match.side_effect = preview
        status, text, rows = self.invoke(["--dry-run"])
        self.assertEqual(status, 0)
        self.assertEqual([row["candidates_count"] for row in rows], [1, 1])
        self.assertEqual([row["status"] for row in rows], ["DRY_RUN", "DRY_RUN"])
        self.assertIn("Emails sent: 0", text)
        self.send.assert_not_called()
        self.mark.assert_not_called()
        self.assertTrue(all(not path.exists() for path in snapshots))
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).digest(), before)

    def test_process_lock_blocks_second_process(self):
        lock_path = self.database.with_name("vakt_run_all.lock")
        child_code = (
            "import sys; from pathlib import Path; from unittest.mock import patch; "
            "import vakt_run_all as b; b.DATABASE=Path(sys.argv[1]); "
            "guard=patch.object(b, 'run_batch', side_effect=AssertionError('batch must not start')); "
            "guard.start(); raise SystemExit(b.main([]))"
        )
        with batch.batch_lock(lock_path):
            result = subprocess.run(
                [sys.executable, "-B", "-c", child_code, str(self.database)],
                cwd=Path(batch.__file__).parent, capture_output=True, text=True, timeout=20,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("already running", result.stdout)
        self.send.assert_not_called()
        self.mark.assert_not_called()

    def test_lock_released_on_exception_and_crash(self):
        lock_path = self.database.with_name("vakt_run_all.lock")
        with self.assertRaises(RuntimeError):
            with batch.batch_lock(lock_path):
                raise RuntimeError("test")
        with batch.batch_lock(lock_path):
            pass
        # Abrupt child exit bypasses finally; the OS must still release the lock.
        child_code = (
            "import os,sys\nfrom vakt_run_all import batch_lock\n"
            "with batch_lock(sys.argv[1]):\n    os._exit(0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", child_code, str(lock_path)],
            cwd=Path(batch.__file__).parent, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(lock_path.exists())
        with batch.batch_lock(lock_path):
            pass


if __name__ == "__main__":
    unittest.main()
