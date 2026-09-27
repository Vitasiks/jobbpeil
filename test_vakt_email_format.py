"""Multipart Vakt email checks; SMTP and POST storage are mocked."""
import io
import os
import unittest
from email import policy
from email.parser import BytesParser
from html import escape
from html.parser import HTMLParser
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import web_app


class EmailHTML(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.links = []
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs)["href"])


class VaktEmailFormatTests(unittest.TestCase):
    def setUp(self):
        environment = {
            "JOBBPEIL_SMTP_HOST": "mail.test.local",
            "JOBBPEIL_SMTP_PORT": "587",
            "JOBBPEIL_SMTP_USER": "test-user",
            "JOBBPEIL_SMTP_PASSWORD": "private-smtp-test-secret",
            "JOBBPEIL_MAIL_FROM": "kontakt@jobbpeil.no",
            "JOBBPEIL_PUBLIC_BASE_URL": "https://jobs.example.test",
        }
        env_patch = patch.dict(os.environ, environment, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        smtp_patch = patch("web_app.smtplib.SMTP")
        self.smtp_constructor = smtp_patch.start()
        self.addCleanup(smtp_patch.stop)
        self.smtp = self.smtp_constructor.return_value.__enter__.return_value
        context_patch = patch("web_app.ssl.create_default_context")
        self.context_factory = context_patch.start()
        self.addCleanup(context_patch.stop)
        self.subscription = {"id": 1, "email": "reader@example.test",
                             "profession_query": "Renholder", "fylke": "Rogaland",
                             "unsubscribe_token": "unsubscribe+token/?=test"}
        self.candidates = [
            {"vacancy_uuid": "a", "title": "Renholder på dagtid", "employer": "Rent & Fint",
             "locations": [{"municipal": "Stavanger", "county": "Rogaland"}],
             "published_date": "24. sep. 2026", "detail_url": "/?q=Renholder&job=a"},
            {"vacancy_uuid": "b", "title": "Renholdsmedarbeider", "employer": None,
             "locations": [], "published_date": None,
             "detail_url": "https://jobs.example.test/?q=Renholder&job=b"},
        ]

    def message_parts(self):
        self.smtp_constructor.assert_called_once_with("mail.test.local", 587, timeout=20)
        self.smtp.send_message.assert_called_once()
        self.assertEqual([call[0] for call in self.smtp.method_calls],
                         ["ehlo", "starttls", "ehlo", "login", "send_message"])
        self.context_factory.assert_called_once_with()
        self.smtp.starttls.assert_called_once_with(context=self.context_factory.return_value)
        self.smtp.login.assert_called_once_with("test-user", "private-smtp-test-secret")
        message = self.smtp.send_message.call_args.args[0]
        parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
        self.assertEqual(parsed.get_content_type(), "multipart/alternative")
        self.assertEqual([part.get_content_type() for part in parsed.iter_parts()],
                         ["text/plain", "text/html"])
        plain_part = parsed.get_body(preferencelist=("plain",))
        html_part = parsed.get_body(preferencelist=("html",))
        self.assertEqual(plain_part.get_content_charset(), "utf-8")
        self.assertEqual(html_part.get_content_charset(), "utf-8")
        text, html = plain_part.get_content(), html_part.get_content()
        self.assertNotIn("private-smtp-test-secret", text + html)
        self.assertEqual(str(parsed["From"]), "JobbPeil <kontakt@jobbpeil.no>")
        self.assertEqual(str(parsed["Reply-To"]), "kontakt@jobbpeil.no")
        self.assertEqual(str(parsed["To"]), "reader@example.test")
        document = EmailHTML(html)
        for prohibited in ("script", "img", "link", "style"):
            self.assertNotIn(prohibited, document.tags)
        return parsed, text, html, document

    def test_confirmation_multipart_context_and_cta(self):
        web_app.send_vakt_confirmation_email("reader@example.test", "verify+/?=token",
                                             profession_query="Sjåfør", fylke="Agder")
        message, text, html, document = self.message_parts()
        self.assertEqual(str(message["Subject"]), "Bekreft JobbPeil Vakt – Sjåfør i Agder")
        url = "https://jobs.example.test/?mode=vakt_verify&token=verify%2B%2F%3F%3Dtoken"
        self.assertIn(url, text)
        self.assertIn(url, document.links)
        for value in ("Sjåfør", "Agder", "Du følger", "Finn din retning", "Bekreft JobbPeil Vakt"):
            self.assertIn(value, text)
            self.assertIn(value, html)
        self.assertIn("background-color:#087a61", html)

    def test_confirmation_two_argument_compatibility(self):
        web_app.send_vakt_confirmation_email("reader@example.test", "existing-token")
        message, text, html, _ = self.message_parts()
        self.assertEqual(str(message["Subject"]), "Bekreft JobbPeil Vakt")
        self.assertIn("existing-token", text)
        self.assertNotIn("Du følger", html)

    def test_alert_multipart_subject_links_optional_fields(self):
        self.assertIs(web_app.send_vakt_job_alert_email(self.subscription, self.candidates), True)
        message, text, html, document = self.message_parts()
        self.assertEqual(str(message["Subject"]), "2 nye jobber for Renholder i Rogaland")
        for candidate in self.candidates:
            self.assertIn(candidate["title"], text)
            self.assertIn(candidate["title"], html)
        for url in ("https://jobs.example.test/?q=Renholder&job=a",
                    "https://jobs.example.test/?q=Renholder&job=b",
                    "https://jobs.example.test/?mode=vakt_unsubscribe&token=unsubscribe%2Btoken%2F%3F%3Dtest"):
            self.assertIn(url, text)
            self.assertIn(url, document.links)
        self.assertEqual(html.count("Se stillingen"), 2)
        self.assertEqual(html.count("Publisert:"), 1)
        self.assertEqual(html.count("📍"), 1)
        self.assertIn("Rent &amp; Fint", html)
        self.assertNotIn("None", text + html)
        self.assertNotIn("vacancy_uuid", text + html)
        self.assertNotIn("relevance", text + html)
        self.assertIn("Meld deg av JobbPeil Vakt", html)

    def test_singular_subject(self):
        web_app.send_vakt_job_alert_email(self.subscription, self.candidates[:1])
        message, _, _, _ = self.message_parts()
        self.assertEqual(str(message["Subject"]), "1 ny jobb for Renholder i Rogaland")

    def test_four_candidate_limit_and_html_escaping(self):
        unsafe = '<script>alert("test")</script> & text'
        self.subscription["profession_query"] = unsafe
        self.candidates[0]["title"] = unsafe
        web_app.send_vakt_job_alert_email(self.subscription, self.candidates * 3)
        message, text, html, _ = self.message_parts()
        self.assertTrue(str(message["Subject"]).startswith("4 nye jobber"))
        self.assertEqual(html.count("Se stillingen"), 4)
        self.assertIn(unsafe, text)
        self.assertIn(escape(unsafe, quote=True), html)
        self.assertNotIn("<script>", html)

    def test_empty_candidates_do_not_connect(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(web_app.send_vakt_job_alert_email(self.subscription, []), False)
        self.smtp_constructor.assert_not_called()

    def test_post_passes_context_and_saved_token(self):
        payload = urlencode({"profession": "Sjåfør", "county": "Agder",
                             "email": "reader@example.test"}).encode("utf-8")
        handler = Mock()
        handler.path = "/?mode=vakt"
        handler.headers = {"Content-Type": "application/x-www-form-urlencoded",
                           "Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        saved = {"email": "reader@example.test", "verification_token": "already-saved-token",
                 "active": False, "status": "created"}
        with patch("web_app.save_vakt_subscription", return_value=saved) as save, \
                patch("web_app.send_vakt_confirmation_email") as send:
            web_app.Handler.do_POST(handler)
        save.assert_called_once()
        send.assert_called_once_with("reader@example.test", "already-saved-token",
                                     profession_query="Sjåfør", fylke="Agder")
        handler.send_response.assert_called_once_with(303)
        self.smtp_constructor.assert_not_called()

    def test_activation_text(self):
        self.assertEqual(web_app.t("no", "vakt.verify_success_copy"),
                         "Vakten er aktiv. Du får e-post når JobbPeil finner nye relevante stillinger for deg.")


if __name__ == "__main__":
    unittest.main()
