"""Render real email templates and mock only Resend's network boundary."""

import base64
import json
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.template import Context, Engine

from .mail import ResendEmailAdapter

TEMPLATE_DIR = Path(__file__).parent / "templates"
MAIL_SETTINGS = {
    "RESEND_API_KEY": "test-resend-key",
    "RESEND_FROM_EMAIL": "AnonymoKE <noreply@anonymoke.co.ke>",
    "RESEND_REPLY_TO_EMAIL": "",
    "MAGIC_LINK_BASE_URL": "anonymoke://auth/magic-link?token=",
    "MAGIC_LINK_TTL_MINUTES": 10,
    "EMAIL_PRIVACY_URL": "",
    "EMAIL_TERMS_URL": "",
}


class EmailLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.images = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a":
            self.links.append(attributes.get("href"))
        if tag == "img":
            self.images.append(attributes.get("src"))


class BrandedMagicLinkEmailTests(TestCase):
    def setUp(self):
        self.config = SimpleNamespace(**MAIL_SETTINGS)
        self.enterContext(patch("apps.accounts.mail.settings", self.config))
        engine = Engine(dirs=[str(TEMPLATE_DIR)])
        self.enterContext(
            patch(
                "apps.accounts.mail.render_to_string",
                side_effect=lambda name, context: engine.get_template(name).render(
                    Context(context, use_l10n=False, use_tz=False)
                ),
            )
        )
        self.urlopen = self.enterContext(patch("apps.accounts.mail.request.urlopen"))
        response = MagicMock()
        response.read.return_value = b'{"id": "message-123"}'
        self.urlopen.return_value.__enter__.return_value = response

    def send(self, token=None):
        token = "test-token" if token is None else token
        result = ResendEmailAdapter().send_magic_link("person@example.test", token)
        request = self.urlopen.call_args.args[0]
        return result, json.loads(request.data)

    def test_html_and_text_use_the_same_private_one_time_link(self):
        result, message = self.send()
        self.assertEqual(result, "message-123")
        self.assertEqual(message["from"], MAIL_SETTINGS["RESEND_FROM_EMAIL"])
        self.assertEqual(message["to"], ["person@example.test"])
        self.assertEqual(message["subject"], "Your AnonymoKE sign-in link")
        sign_in = "anonymoke://auth/magic-link?token=test-token"
        self.assertEqual(EmailLinks(message["html"]).links.count(sign_in), 2)
        self.assertIn(sign_in, message["text"])
        for body in (message["html"], message["text"]):
            self.assertIn("10 minutes", body)
            self.assertIn("Can only be used once", body)
            self.assertIn("Never forward this email", body)
            self.assertIn("you can safely ignore it", body)
            self.assertIn("Private by choice", body)
            self.assertNotIn("test-resend-key", body)
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-resend-key")
        self.assertEqual(
            request.get_header("User-agent"), "AnonymoKE/1.0 (+https://anonymoke.co.ke)"
        )
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(self.urlopen.call_args.kwargs["timeout"], 10)

    def test_expiry_matches_the_server_configuration_in_both_versions(self):
        for minutes in (1, 17):
            with self.subTest(minutes=minutes):
                self.config.MAGIC_LINK_TTL_MINUTES = minutes
                _, message = self.send()
                for body in (message["html"], message["text"]):
                    self.assertIn(
                        f"Expires in {minutes} minute{'s' if minutes != 1 else ''}.", body
                    )

    def test_logo_is_embedded_without_a_remote_image_or_tracking_request(self):
        _, message = self.send()
        (attachment,) = message["attachments"]
        self.assertEqual(EmailLinks(message["html"]).images, ["cid:anonymoke-logo"])
        self.assertEqual(attachment["content_id"], "anonymoke-logo")
        self.assertEqual(attachment["content_type"], "image/jpeg")
        self.assertTrue(attachment["filename"].endswith(".jpeg"))
        self.assertEqual(
            base64.b64decode(attachment["content"], validate=True),
            (Path(__file__).parent / "resources" / "anonymoke-logo.jpeg").read_bytes(),
        )

    def test_token_is_url_encoded_and_template_values_are_html_escaped(self):
        self.config.MAGIC_LINK_BASE_URL = (
            'https://auth.example.test/auth/magic-link?label="<unsafe>"&token='
        )
        _, message = self.send('abc/&"<>')
        expected = (
            'https://auth.example.test/auth/magic-link?label="<unsafe>"&token=abc%2F%26%22%3C%3E'
        )
        self.assertEqual(EmailLinks(message["html"]).links.count(expected), 2)
        self.assertIn(expected, message["text"])
        self.assertNotIn("<unsafe>", message["html"])
        self.assertIn("&lt;unsafe&gt;", message["html"])

    def test_unconfigured_support_and_policy_links_are_omitted(self):
        _, message = self.send()
        self.assertNotIn("reply_to", message)
        self.assertEqual(
            EmailLinks(message["html"]).links,
            [
                "anonymoke://auth/magic-link?token=test-token",
                "anonymoke://auth/magic-link?token=test-token",
                "https://anonymoke.co.ke",
            ],
        )
        for value in ("Privacy:", "Terms:", "Support:"):
            self.assertNotIn(value, message["text"])

    def test_configured_reply_address_and_policy_links_are_in_the_footer(self):
        self.config.RESEND_REPLY_TO_EMAIL = "support@example.test"
        self.config.EMAIL_PRIVACY_URL = "https://example.test/privacy"
        self.config.EMAIL_TERMS_URL = "https://example.test/terms"
        _, message = self.send()
        self.assertEqual(message["reply_to"], "support@example.test")
        links = EmailLinks(message["html"]).links
        self.assertIn("mailto:support@example.test", links)
        for url in (self.config.EMAIL_PRIVACY_URL, self.config.EMAIL_TERMS_URL):
            self.assertIn(url, links)
            self.assertIn(url, message["text"])

    def test_missing_api_key_fails_without_contacting_resend(self):
        self.config.RESEND_API_KEY = ""
        with self.assertRaisesRegex(RuntimeError, "resend_not_configured"):
            self.send()
        self.urlopen.assert_not_called()

    def test_provider_failure_is_not_reported_as_delivery_success(self):
        self.urlopen.side_effect = URLError("offline")
        with self.assertRaises(URLError):
            self.send()

    def test_rejected_delivery_logs_status_without_recipient_or_token_details(self):
        self.urlopen.side_effect = HTTPError(
            "https://api.resend.com/emails",
            403,
            "person@example.test test-token test-resend-key",
            {},
            None,
        )
        with self.assertLogs("anonymoke.accounts.email", level="WARNING") as captured:
            with self.assertRaises(HTTPError):
                self.send()
        output = " ".join(captured.output)
        self.assertIn("http_status=403", output)
        for private in ("person@example.test", "test-token", "test-resend-key"):
            self.assertNotIn(private, output)

    def test_provider_success_requires_a_nonempty_message_id(self):
        for body in (b"{}", b'{"id": ""}', b'{"id": null}', b"[]"):
            with self.subTest(body=body):
                self.urlopen.return_value.__enter__.return_value.read.return_value = body
                with self.assertLogs("anonymoke.accounts.email", level="WARNING"):
                    with self.assertRaisesRegex(ValueError, "resend_invalid_response"):
                        self.send()
