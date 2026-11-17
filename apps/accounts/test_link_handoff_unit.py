"""Exercise the public handoff without a database, GIS or a real sign-in token."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from django.template import Context, Engine

from .link_handoff import android_asset_links, magic_link_landing

CERTIFICATE = (
    "D6:D8:9F:61:38:46:F1:78:2B:81:78:3D:6D:C7:80:68:"
    "5B:64:1B:76:7C:DF:70:25:13:CA:AF:48:94:0F:E6:5F"
)


class MagicLinkHandoffTests(TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            MAGIC_LINK_TTL_MINUTES=10,
            ANDROID_APP_LINK_SHA256_FINGERPRINTS=[CERTIFICATE],
        )
        self.enterContext(patch("apps.accounts.link_handoff.settings", self.config))
        engine = Engine(dirs=[str(Path(__file__).parent / "templates")])
        self.enterContext(
            patch(
                "apps.accounts.link_handoff.render_to_string",
                side_effect=lambda name, context: engine.get_template(name).render(
                    Context(context, use_l10n=False, use_tz=False)
                ),
            )
        )

    def test_landing_renders_without_reading_or_redeeming_a_token(self):
        # No GET/body/session attributes: the view must not need any of them.
        response = magic_link_landing(SimpleNamespace(method="GET"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Open AnonymoKE", body)
        self.assertIn('id="open-app" class="button" rel="noreferrer" hidden', body)
        self.assertIn("expires in 10 minutes and works once", body)
        self.assertIn("data:image/jpeg;base64,", body)
        self.assertNotIn("/api/v1/auth/magic-link/verify/", body)
        self.assertNotIn("fetch(", body)
        self.assertNotIn("window.location.assign", body)

    def test_landing_never_caches_or_exposes_referrers_and_uses_nonce_csp(self):
        first = magic_link_landing(SimpleNamespace(method="GET"))
        second = magic_link_landing(SimpleNamespace(method="GET"))
        self.assertIn("no-store", first["Cache-Control"])
        self.assertEqual(first["Referrer-Policy"], "no-referrer")
        self.assertEqual(first["X-Frame-Options"], "DENY")
        self.assertEqual(first["X-Content-Type-Options"], "nosniff")
        self.assertIn("noindex", first["X-Robots-Tag"])
        csp = first["Content-Security-Policy"]
        nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
        self.assertIn(f'<script nonce="{nonce}">', first.content.decode())
        self.assertIn(f'<style nonce="{nonce}">', first.content.decode())
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotEqual(csp, second["Content-Security-Policy"])

    def test_landing_head_is_empty_and_post_is_rejected(self):
        response = magic_link_landing(SimpleNamespace(method="HEAD"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        response = magic_link_landing(SimpleNamespace(method="POST"))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "GET, HEAD")

    def test_asset_links_use_the_correct_package_and_signing_certificate(self):
        response = android_asset_links(SimpleNamespace(method="GET"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        (association,) = json.loads(response.content)
        self.assertEqual(association["relation"], ["delegate_permission/common.handle_all_urls"])
        self.assertEqual(association["target"]["namespace"], "android_app")
        self.assertEqual(association["target"]["package_name"], "co.anonymoke.anonymoke")
        self.assertEqual(association["target"]["sha256_cert_fingerprints"], [CERTIFICATE])

    def test_certificates_are_normalized_and_duplicates_removed(self):
        self.config.ANDROID_APP_LINK_SHA256_FINGERPRINTS = [
            CERTIFICATE.lower(),
            " " + CERTIFICATE + " ",
        ]
        response = android_asset_links(SimpleNamespace(method="GET"))
        self.assertEqual(
            json.loads(response.content)[0]["target"]["sha256_cert_fingerprints"], [CERTIFICATE]
        )

    def test_empty_or_invalid_certificate_configuration_does_not_publish_an_association(self):
        for certificates in ([], ["incorrect"], [CERTIFICATE, "incorrect"]):
            with self.subTest(certificates=certificates):
                self.config.ANDROID_APP_LINK_SHA256_FINGERPRINTS = certificates
                response = android_asset_links(SimpleNamespace(method="GET"))
                self.assertEqual(response.status_code, 503)
                self.assertEqual(json.loads(response.content), [])
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_asset_links_head_is_empty_and_post_is_rejected(self):
        response = android_asset_links(SimpleNamespace(method="HEAD"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        response = android_asset_links(SimpleNamespace(method="POST"))
        self.assertEqual(response.status_code, 405)
