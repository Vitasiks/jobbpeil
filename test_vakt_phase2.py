import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

import vakt_run_all
import web_app
from nav_database import initialize_database


class VaktPhase2Tests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "vakt.db"
        initialize_database(self.database)
        with sqlite3.connect(self.database) as db:
            db.execute(
                "INSERT INTO vakt_subscriptions "
                "(id,email,profession_query,profession_query_key,fylke,active,created_at,"
                "verified_at,verification_token,unsubscribe_token) VALUES "
                "(1,'reader@example.test','Kokk','kokk','Vestfold',1,?,?,?,?)",
                ("2026-09-20T10:00:00+00:00", "2026-09-20T10:00:00+00:00", "verify", "unsubscribe"),
            )

    def tearDown(self):
        self.tempdir.cleanup()

    def subscription(self):
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            return dict(db.execute(
                "SELECT * FROM vakt_subscriptions WHERE id=1"
            ).fetchone())

    def candidate(self, uuid="job-1"):
        return {"vacancy_uuid": uuid, "title": "Kokk", "employer": "Test",
                "fylke": "Vestfold", "locations": [], "detail_url": "/?job=" + uuid}

    WEDNESDAY = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)

    def plan(self, strict=None, fallback=None, regional=None, now=None, last_email=None,
             last_status=None):
        now = now or self.WEDNESDAY
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE vakt_subscriptions SET last_vakt_email_at=?, "
                       "last_status_email_at=? WHERE id=1", (last_email, last_status))
        with patch("web_app.get_vakt_candidate_sets", return_value=(strict or [], fallback or [])), \
             patch("web_app._vakt_regional_candidates", return_value=regional or []):
            return web_app.vakt_delivery_plan(self.subscription(), self.database, now=now)

    def test_strict_new_mode(self):
        result = self.plan(strict=[self.candidate()])
        self.assertEqual(result["mode"], "NEW_STRICT")
        self.assertEqual(result["strict"], [self.candidate()])

    def test_fallback_new_mode(self):
        result = self.plan(fallback=[self.candidate()])
        self.assertEqual(result["mode"], "FALLBACK")

    def test_regional_status_mode(self):
        result = self.plan(regional=[self.candidate("regional")])
        self.assertEqual(result["mode"], "REGIONAL_STATUS")
        self.assertEqual(len(result["regional"]), 1)

    def test_regional_is_limited_by_provider_to_three(self):
        regional = [self.candidate(str(index)) for index in range(3)]
        result = self.plan(regional=regional)
        self.assertEqual(len(result["regional"]), 3)

    def test_first_no_new_allows_heartbeat(self):
        result = self.plan(now=datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(result["mode"], "HEARTBEAT")

    def test_second_no_new_before_seven_days_is_skipped(self):
        last = "2026-09-29T12:00:00+00:00"
        result = self.plan(now=datetime(2026, 9, 30, tzinfo=timezone.utc), last_status=last)
        self.assertEqual(result["mode"], "NO_NEW_SKIPPED_RECENT_STATUS")

    def test_heartbeat_after_seven_days(self):
        last = "2026-09-23T12:00:00+00:00"
        result = self.plan(now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc), last_status=last)
        self.assertEqual(result["mode"], "HEARTBEAT")

    def test_fallback_blocked_by_recent_status(self):
        result = self.plan(fallback=[self.candidate()], last_status="2026-09-29T12:00:00+00:00")
        self.assertEqual(result["mode"], "NO_NEW_SKIPPED_RECENT_STATUS")

    # --- no-new-jobs cadence (A-I) ---
    SATURDAY = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    SUNDAY = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    MONDAY = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)

    def test_a_new_job_sends_normal_alert(self):
        self.assertEqual(self.plan(strict=[self.candidate()])["mode"], "NEW_STRICT")

    def test_b_status_yesterday_blocks_fallback(self):
        result = self.plan(fallback=[self.candidate()], last_status="2026-09-29T12:00:00+00:00")
        self.assertEqual(result["mode"], "NO_NEW_SKIPPED_RECENT_STATUS")

    def test_c_six_days_blocks_fallback(self):
        result = self.plan(fallback=[self.candidate()], last_status="2026-09-24T12:00:00+00:00")
        self.assertEqual(result["mode"], "NO_NEW_SKIPPED_RECENT_STATUS")

    def test_d_seven_days_weekday_sends_fallback(self):
        result = self.plan(fallback=[self.candidate()], last_status="2026-09-23T12:00:00+00:00")
        self.assertEqual(result["mode"], "FALLBACK")

    def test_e_weekend_blocks_fallback(self):
        for now in (self.SATURDAY, self.SUNDAY):
            result = self.plan(fallback=[self.candidate()], now=now,
                               last_status="2026-09-20T12:00:00+00:00")
            self.assertEqual(result["mode"], "NO_NEW_SKIPPED_RECENT_STATUS")

    def test_f_monday_after_weekend_sends_fallback(self):
        result = self.plan(fallback=[self.candidate()], now=self.MONDAY,
                           last_status="2026-09-28T12:00:00+00:00")
        self.assertEqual(result["mode"], "FALLBACK")

    def test_g_new_job_ignores_status_cooldown_and_weekend(self):
        for now in (self.WEDNESDAY, self.SUNDAY):
            result = self.plan(strict=[self.candidate()], now=now,
                               last_status=(now - timedelta(days=1)).isoformat())
            self.assertEqual(result["mode"], "NEW_STRICT")

    def test_h_subscriptions_are_independent(self):
        with sqlite3.connect(self.database) as db:
            db.execute(
                "INSERT INTO vakt_subscriptions "
                "(id,email,profession_query,profession_query_key,fylke,active,created_at,"
                "verified_at,verification_token,unsubscribe_token,last_status_email_at) VALUES "
                "(2,'other@example.test','Kokk','kokk','Vestfold',1,?,?,?,?,?)",
                ("2026-09-20T10:00:00+00:00", "2026-09-20T10:00:00+00:00", "v2", "u2",
                 "2026-09-29T12:00:00+00:00"),
            )
            db.execute("UPDATE vakt_subscriptions SET last_status_email_at=? WHERE id=1",
                       ("2026-09-20T12:00:00+00:00",))
            db.row_factory = sqlite3.Row
            subs = [dict(db.execute("SELECT * FROM vakt_subscriptions WHERE id=?", (i,)).fetchone())
                    for i in (1, 2)]
        with patch("web_app.get_vakt_candidate_sets", return_value=([], [self.candidate()])):
            modes = [web_app.vakt_delivery_plan(s, self.database, now=self.WEDNESDAY)["mode"]
                     for s in subs]
        self.assertEqual(modes, ["FALLBACK", "NO_NEW_SKIPPED_RECENT_STATUS"])

    def test_i_smtp_failure_does_not_record_status(self):
        plan = {"mode": "FALLBACK", "strict": [], "fallback": [self.candidate()], "regional": []}
        with patch.object(vakt_run_all, "vakt_delivery_plan", return_value=plan), \
             patch.object(vakt_run_all, "send_vakt_job_alert_email", return_value=False), \
             patch.object(vakt_run_all, "get_vakt_candidates", return_value=[]):
            vakt_run_all.run_batch(self.database)
        row = self.subscription()
        self.assertIsNone(row["last_status_email_at"])
        self.assertIsNone(row["last_vakt_email_at"])

    def test_regional_empty_still_heartbeat(self):
        result = self.plan(now=datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(result["mode"], "HEARTBEAT")
        self.assertEqual(result["regional"], [])

    def test_inactive_subscription_has_no_candidates(self):
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE vakt_subscriptions SET active=0 WHERE id=1")
        result = web_app.vakt_delivery_plan(self.subscription(), self.database)
        self.assertEqual(result["mode"], "INACTIVE")
        self.assertEqual(web_app.get_vakt_candidates({"id": 1}, database=self.database), [])

    def test_pending_subscription_has_no_candidates(self):
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE vakt_subscriptions SET active=0, verified_at=NULL WHERE id=1")
        self.assertEqual(web_app.get_vakt_candidates({"id": 1}, database=self.database), [])

    def test_update_strict_timestamp_does_not_change_status_timestamp(self):
        old_status = "2026-09-01T10:00:00+00:00"
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE vakt_subscriptions SET last_status_email_at=? WHERE id=1", (old_status,))
        sent = "2026-09-30T10:00:00+00:00"
        web_app.update_vakt_communication(1, "NEW_STRICT", sent, self.database)
        row = self.subscription()
        self.assertEqual(row["last_vakt_email_at"], sent)
        self.assertEqual(row["last_status_email_at"], old_status)

    def test_update_status_updates_both_timestamps(self):
        sent = "2026-09-30T10:00:00+00:00"
        web_app.update_vakt_communication(1, "HEARTBEAT", sent, self.database)
        row = self.subscription()
        self.assertEqual(row["last_vakt_email_at"], sent)
        self.assertEqual(row["last_status_email_at"], sent)

    def test_migration_is_idempotent_and_old_rows_are_preserved(self):
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE vakt_subscriptions SET profession_query='Preserved' WHERE id=1")
        initialize_database(self.database)
        initialize_database(self.database)
        row = self.subscription()
        self.assertEqual(row["profession_query"], "Preserved")
        self.assertIsNone(row["last_vakt_email_at"])
        self.assertIsNone(row["last_status_email_at"])

    def test_smtp_failure_does_not_write_state_or_sent_jobs(self):
        plan = {"mode": "FALLBACK", "strict": [], "fallback": [self.candidate()], "regional": []}
        with patch.object(vakt_run_all, "DATABASE", self.database), \
             patch.object(vakt_run_all, "vakt_delivery_plan", return_value=plan), \
             patch.object(vakt_run_all, "send_vakt_job_alert_email", side_effect=RuntimeError("smtp")):
            self.assertEqual(vakt_run_all.run_batch(self.database), 1)
        row = self.subscription()
        with sqlite3.connect(self.database) as db:
            sent_count = db.execute("SELECT COUNT(*) FROM vakt_sent_jobs").fetchone()[0]
        self.assertIsNone(row["last_vakt_email_at"])
        self.assertIsNone(row["last_status_email_at"])
        self.assertEqual(sent_count, 0)

    def test_success_writes_sent_jobs_and_state(self):
        plan = {"mode": "REGIONAL_STATUS", "strict": [], "fallback": [],
                "regional": [self.candidate("regional")]}
        with patch.object(vakt_run_all, "DATABASE", self.database), \
             patch.object(vakt_run_all, "vakt_delivery_plan", return_value=plan), \
             patch.object(vakt_run_all, "send_vakt_job_alert_email", return_value=True):
            self.assertEqual(vakt_run_all.run_batch(self.database), 0)
        row = self.subscription()
        with sqlite3.connect(self.database) as db:
            sent_count = db.execute("SELECT COUNT(*) FROM vakt_sent_jobs").fetchone()[0]
        self.assertIsNotNone(row["last_vakt_email_at"])
        self.assertIsNotNone(row["last_status_email_at"])
        self.assertEqual(sent_count, 1)

    def test_fallback_email_subject_and_copy(self):
        config = {"JOBBPEIL_SMTP_HOST": "mail", "JOBBPEIL_SMTP_PORT": 587,
                  "JOBBPEIL_SMTP_USER": "user", "JOBBPEIL_SMTP_PASSWORD": "secret",
                  "JOBBPEIL_MAIL_FROM": "kontakt@jobbpeil.no", "JOBBPEIL_PUBLIC_BASE_URL": "https://jobbpeil.no"}
        with patch("web_app._vakt_mail_config", return_value=config), \
             patch("web_app._send_vakt_email_message") as send:
            self.assertTrue(web_app.send_vakt_job_alert_email(self.subscription(), [self.candidate()], "FALLBACK"))
        message = send.call_args.args[0]
        text = message.get_body(preferencelist=("plain",)).get_content()
        self.assertEqual(str(message["Subject"]), "JobbPeil Vakt følger fortsatt med")
        self.assertIn("ingen nye stillinger", text)

    def test_regional_email_does_not_claim_match(self):
        config = {"JOBBPEIL_SMTP_HOST": "mail", "JOBBPEIL_SMTP_PORT": 587,
                  "JOBBPEIL_SMTP_USER": "user", "JOBBPEIL_SMTP_PASSWORD": "secret",
                  "JOBBPEIL_MAIL_FROM": "kontakt@jobbpeil.no", "JOBBPEIL_PUBLIC_BASE_URL": "https://jobbpeil.no"}
        with patch("web_app._vakt_mail_config", return_value=config), \
             patch("web_app._send_vakt_email_message") as send:
            web_app.send_vakt_job_alert_email(self.subscription(), [self.candidate()], "REGIONAL_STATUS")
        text = send.call_args.args[0].get_body(preferencelist=("plain",)).get_content()
        self.assertIn("andre aktuelle stillinger", text)
        self.assertNotIn("som kan passe med det du følger", text)

    def test_heartbeat_email_has_no_cards(self):
        config = {"JOBBPEIL_SMTP_HOST": "mail", "JOBBPEIL_SMTP_PORT": 587,
                  "JOBBPEIL_SMTP_USER": "user", "JOBBPEIL_SMTP_PASSWORD": "secret",
                  "JOBBPEIL_MAIL_FROM": "kontakt@jobbpeil.no", "JOBBPEIL_PUBLIC_BASE_URL": "https://jobbpeil.no"}
        with patch("web_app._vakt_mail_config", return_value=config), \
             patch("web_app._send_vakt_email_message") as send:
            self.assertTrue(web_app.send_vakt_job_alert_email(self.subscription(), [], "HEARTBEAT"))
        text = send.call_args.args[0].get_body(preferencelist=("plain",)).get_content()
        self.assertIn("ikke funnet nye stillinger", text)
        self.assertNotIn("1. ", text)


if __name__ == "__main__":
    unittest.main()
