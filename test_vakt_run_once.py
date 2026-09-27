"""Isolated runner tests: temporary SQLite only, SMTP always blocked."""
from contextlib import closing, redirect_stdout, redirect_stderr
import hashlib
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from nav_database import initialize_database
import vakt_run_once as runner


class VaktRunnerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="vakt-runner-test-")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "source.db"
        initialize_database(self.database)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            for sid, email, active, verified in (
                (1, "reader@example.test", 1, "2026-09-24T08:00:00+00:00"),
                (2, "reader@example.test", 0, None),
                (3, "reader@example.test", 1, None),
                (4, "another@example.test", 1, "2026-09-24T08:00:00+00:00"),
                (5, "reader@example.test", 1, "2026-09-24T08:00:00+00:00"),
            ):
                connection.execute(
                    "INSERT INTO vakt_subscriptions "
                    "(id,email,profession_query,profession_query_key,fylke,active,"
                    "created_at,verified_at,verification_token,unsubscribe_token) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (sid, email, f"Profession {sid}", f"profession {sid}", "Oslo",
                     active, "2026-09-24T07:00:00+00:00", verified,
                     f"private-verify-{sid}", f"private-unsubscribe-{sid}"),
                )
        self.start_patch("vakt_run_once.DATABASE", self.database)
        self.smtp = self.start_patch(
            "web_app.smtplib.SMTP", side_effect=AssertionError("Real SMTP forbidden"))
        self.match = self.start_patch("vakt_run_once.get_vakt_candidates")
        self.send = self.start_patch("vakt_run_once.send_vakt_job_alert_email", return_value=True)
        self.mark = self.start_patch("vakt_run_once.mark_vakt_jobs_sent", return_value=2)
        self.candidates = [self.candidate("first"), self.candidate("second")]
        self.match.return_value = self.candidates

    def start_patch(self, target, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    @staticmethod
    def candidate(uuid):
        return {"vacancy_uuid": uuid, "title": "Test vacancy " + uuid,
                "employer": "Test employer", "fylke": "Oslo"}

    def invoke(self, arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            status = runner.main(arguments)
        self.smtp.assert_not_called()
        self.assertNotIn("private-", output.getvalue())
        return status, output.getvalue()

    def test_list_mode(self):
        before = hashlib.sha256(self.database.read_bytes()).digest()
        status, output = self.invoke(["--list", "--email", "reader@example.test"])
        self.assertEqual(status, 0)
        self.assertIn('"id": 1', output)
        self.assertIn('"id": 5', output)
        for sid in (2, 3, 4):
            self.assertNotIn(f'"id": {sid}', output)
        self.match.assert_not_called()
        self.send.assert_not_called()
        self.mark.assert_not_called()
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).digest(), before)

    def test_dry_run_uses_disposable_copy(self):
        before = hashlib.sha256(self.database.read_bytes()).digest()
        snapshots = []

        def matching(subscription, limit, database):
            self.assertEqual(subscription["id"], 1)
            self.assertEqual(limit, 4)
            self.assertNotEqual(database, self.database)
            snapshots.append(database)
            # Exercise the existing matching initialization's write permissions
            # without touching the original source DB or loading live job data.
            initialize_database(database)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("CREATE TABLE dry_run_probe (value TEXT)")
            return self.candidates

        self.match.side_effect = matching
        status, output = self.invoke(["--subscription-id", "1", "--dry-run"])
        self.assertEqual(status, 0)
        self.assertIn("Dry run:", output)
        self.match.assert_called_once()
        self.send.assert_not_called()
        self.mark.assert_not_called()
        self.assertTrue(snapshots)
        self.assertTrue(all(not path.exists() for path in snapshots))
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).digest(), before)

    def test_no_candidates(self):
        self.match.return_value = []
        status, output = self.invoke(["--subscription-id", "1"])
        self.assertEqual(status, 0)
        self.assertIn("No new candidates.", output)
        self.send.assert_not_called()
        self.mark.assert_not_called()

    def test_smtp_exception_does_not_mark(self):
        self.send.side_effect = RuntimeError("private-password-must-not-leak")
        status, output = self.invoke(["--subscription-id", "1"])
        self.assertEqual(status, 1)
        self.assertIn("Email sending failed (RuntimeError)", output)
        self.send.assert_called_once()
        self.match.assert_called_once()
        self.mark.assert_not_called()

    def test_false_result_does_not_mark(self):
        self.send.return_value = False
        status, output = self.invoke(["--subscription-id", "1"])
        self.assertEqual(status, 1)
        self.assertIn("not confirmed", output)
        self.mark.assert_not_called()
        self.match.assert_called_once()

    def test_success_marks_after_send_and_allows_other_candidates(self):
        self.match.side_effect = [self.candidates, [self.candidate("third")]]
        sequence = Mock()
        sequence.attach_mock(self.match, "matching")
        sequence.attach_mock(self.send, "send")
        sequence.attach_mock(self.mark, "mark")
        status, output = self.invoke(["--subscription-id", "1"])
        self.assertEqual(status, 0)
        self.assertIn("Dedupe check: PASS", output)
        self.assertEqual([item[0] for item in sequence.mock_calls],
                         ["matching", "send", "mark", "matching"])
        subscription = self.send.call_args.args[0]
        self.assertEqual(subscription["id"], 1)
        self.assertEqual(subscription["email"], "reader@example.test")
        self.assertEqual(subscription["unsubscribe_token"], "private-unsubscribe-1")
        self.send.assert_called_once_with(subscription, self.candidates)
        self.mark.assert_called_once_with(1, ["first", "second"], database=self.database)
        for match_call in self.match.call_args_list:
            self.assertEqual(match_call.kwargs, {"limit": 4, "database": self.database})

    def test_dedupe_overlap_fails_without_second_email(self):
        self.match.side_effect = [self.candidates, [self.candidate("second")]]
        status, output = self.invoke(["--subscription-id", "1"])
        self.assertEqual(status, 1)
        self.assertIn("Dedupe check: FAIL", output)
        self.send.assert_called_once()
        self.mark.assert_called_once()

    def test_missing_inactive_or_unverified_never_send(self):
        for sid in (2, 3, 999):
            with self.subTest(subscription_id=sid):
                status, output = self.invoke(["--subscription-id", str(sid)])
                self.assertEqual(status, 1)
                self.assertIn("Nothing sent.", output)
        self.match.assert_not_called()
        self.send.assert_not_called()
        self.mark.assert_not_called()

    def test_invalid_cli_combinations(self):
        for arguments in ([], ["--list"], ["--subscription-id", "0"],
                          ["--subscription-id", "1", "--email", "reader@example.test"],
                          ["--list", "--email", "reader@example.test", "--dry-run"]):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    runner.main(arguments)
                self.assertEqual(error.exception.code, 2)
        self.match.assert_not_called()
        self.send.assert_not_called()
        self.mark.assert_not_called()


if __name__ == "__main__":
    unittest.main()
