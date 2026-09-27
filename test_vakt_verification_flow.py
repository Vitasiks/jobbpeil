"""GET-confirmation and POST-only Vakt verification flow tests."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import web_app
from nav_database import initialize_database


ANALYTICS_MARKER = 'data-analytics-event="vakt_verified"'


def rendered_markup(document):
    return re.sub(r"<script.*?</script>", "", document, flags=re.S)


class VaktVerificationFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="vakt-verify-flow-")
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "synthetic-vakt.db"
        initialize_database(self.database)
        self.valid_token = "V" * 43
        self.expired_token = "E" * 43
        self.valid_unsubscribe_token = "U" * 43
        self.expired_unsubscribe_token = "W" * 43
        valid_expiration = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO vakt_subscriptions "
                "(email, profession_query, profession_query_key, fylke, active, created_at, "
                "verification_token, verification_expires_at, unsubscribe_token) "
                "VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
                ("fake-valid@example.invalid", "renholder", "renholder", "Agder", "test",
                 self.valid_token, valid_expiration, self.valid_unsubscribe_token),
            )
            connection.execute(
                "INSERT INTO vakt_subscriptions "
                "(email, profession_query, profession_query_key, fylke, active, created_at, "
                "verification_token, verification_expires_at, unsubscribe_token) "
                "VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
                ("fake-expired@example.invalid", "kokk", "kokk", "Oslo", "test",
                 self.expired_token, "2000-01-01T00:00:00+00:00", self.expired_unsubscribe_token),
            )
        pending = web_app.vakt_verification_pending
        verify = web_app.verify_vakt_subscription
        unsubscribe = web_app.unsubscribe_vakt_subscription
        patches = (
            patch("web_app.vakt_verification_pending",
                  side_effect=lambda token: pending(token, self.database)),
            patch("web_app.verify_vakt_subscription",
                  side_effect=lambda token: verify(token, self.database)),
            patch("web_app.unsubscribe_vakt_subscription",
                  side_effect=lambda token: unsubscribe(token, self.database)),
            patch.object(web_app.Handler, "log_message", lambda *_args: None),
        )
        self.patchers = patches
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web_app.Handler)
        self.server_thread = Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def get(self, token, mode="vakt_verify"):
        url = f"{self.base_url}/?{urlencode({'mode': mode, 'token': token})}"
        with urlopen(url) as response:
            return response.status, response.headers, response.read().decode("utf-8")

    def post(self, token, mode="vakt_verify"):
        url = f"{self.base_url}/?{urlencode({'mode': mode})}"
        request = Request(url, data=urlencode({"token": token}).encode("utf-8"),
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(request) as response:
            return response.status, response.url, response.headers, response.read().decode("utf-8")

    def subscription(self, token):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute(
                "SELECT active, verified_at, verification_token FROM vakt_subscriptions "
                "WHERE verification_token=?", (token,),
            ).fetchone()

    def subscription_by_identity(self, email):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute(
                "SELECT active, verified_at, verification_token FROM vakt_subscriptions "
                "WHERE email=?", (email,),
            ).fetchone()

    def test_get_valid_token_shows_confirmation_without_mutation(self):
        before = self.subscription(self.valid_token)
        status, headers, document = self.get(self.valid_token)
        after = self.subscription(self.valid_token)
        markup = rendered_markup(document)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIn("Bekreft JobbPeil Vakt", markup)
        self.assertIn("Bekreft Vakt", markup)
        self.assertIn('method="post"', markup)
        self.assertNotIn(ANALYTICS_MARKER, markup)
        self.assertEqual(before, after)
        self.assertEqual(after[0:2], (0, None))
        self.assertEqual(after[2], self.valid_token)
        self.assertNotIn("fake-valid@example.invalid", markup)

    def test_post_valid_token_activates_and_emits_marker(self):
        status, final_url, headers, document = self.post(self.valid_token)
        markup = rendered_markup(document)
        row = self.subscription_by_identity("fake-valid@example.invalid")
        self.assertEqual(status, 200)
        self.assertEqual(final_url, f"{self.base_url}/?mode=vakt_verify")
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIn(ANALYTICS_MARKER, markup)
        self.assertIn("gtag('event', 'vakt_verified');", document)
        self.assertEqual(row[0], 1)
        self.assertIsNotNone(row[1])
        self.assertNotEqual(row[2], self.valid_token)
        self.assertNotIn("fake-valid@example.invalid", markup)
        self.assertNotIn(self.valid_token, document)
        self.assertNotIn(self.valid_unsubscribe_token, document)

    def test_invalid_get_and_post_do_not_activate(self):
        invalid_token = "I" * 43
        before = self.subscription_by_identity("fake-valid@example.invalid")
        get_status, _, get_document = self.get(invalid_token)
        post_status, _, _, post_document = self.post(invalid_token)
        after = self.subscription_by_identity("fake-valid@example.invalid")
        self.assertEqual(get_status, 200)
        self.assertEqual(post_status, 200)
        self.assertNotIn(ANALYTICS_MARKER, rendered_markup(get_document))
        self.assertNotIn(ANALYTICS_MARKER, rendered_markup(post_document))
        self.assertEqual(before, after)

    def test_expired_get_and_post_do_not_activate(self):
        get_status, _, get_document = self.get(self.expired_token)
        post_status, _, _, post_document = self.post(self.expired_token)
        row = self.subscription_by_identity("fake-expired@example.invalid")
        self.assertEqual(get_status, 200)
        self.assertEqual(post_status, 200)
        self.assertNotIn("Bekreft Vakt", rendered_markup(get_document))
        self.assertNotIn(ANALYTICS_MARKER, rendered_markup(post_document))
        self.assertEqual(row[0:2], (0, None))
        self.assertEqual(row[2], self.expired_token)

    def test_repeated_post_and_refresh_cannot_emit_second_marker(self):
        first_status, _, _, first_document = self.post(self.valid_token)
        repeat_status, _, _, repeat_document = self.post(self.valid_token)
        self.assertEqual(first_status, 200)
        self.assertEqual(repeat_status, 200)
        self.assertIn(ANALYTICS_MARKER, rendered_markup(first_document))
        self.assertNotIn(ANALYTICS_MARKER, rendered_markup(repeat_document))

    def test_unsubscribe_route_still_works(self):
        self.post(self.valid_token)
        status, _, document = self.get(self.valid_unsubscribe_token, mode="vakt_unsubscribe")
        row = self.subscription_by_identity("fake-valid@example.invalid")
        self.assertEqual(status, 200)
        self.assertIn("vakt_unsubscribe", document)
        self.assertEqual(row[0], 0)
        self.assertNotIn(ANALYTICS_MARKER, rendered_markup(document))


if __name__ == "__main__":
    unittest.main()