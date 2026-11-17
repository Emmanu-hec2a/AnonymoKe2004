"""Public app-link association and scanner-safe email handoff. No token redemption."""

import base64
import re
import secrets
from importlib.resources import files

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.template.loader import render_to_string

ANDROID_PACKAGE = "co.anonymoke.anonymoke"
_CERTIFICATE = re.compile(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}\Z")


def _method_not_allowed():
    response = HttpResponseNotAllowed(["GET", "HEAD"], charset="utf-8")
    response["Cache-Control"] = "no-store"
    return response


def magic_link_landing(request):
    if request.method not in {"GET", "HEAD"}:
        return _method_not_allowed()

    nonce = secrets.token_urlsafe(24)
    logo = files("apps.accounts").joinpath("resources", "anonymoke-logo.jpeg").read_bytes()
    html = render_to_string(
        "accounts/auth/magic_link_landing.html",
        {
            "nonce": nonce,
            "android_package": ANDROID_PACKAGE,
            "logo_data": base64.b64encode(logo).decode("ascii"),
            "ttl_minutes": settings.MAGIC_LINK_TTL_MINUTES,
        },
    )
    response = HttpResponse(html, content_type="text/html", charset="utf-8")
    response["Cache-Control"] = "no-store, max-age=0"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "DENY"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response["Content-Security-Policy"] = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    if request.method == "HEAD":
        response.content = b""
    return response


def android_asset_links(request):
    if request.method not in {"GET", "HEAD"}:
        return _method_not_allowed()

    certificates = list(
        dict.fromkeys(
            value.strip().upper() for value in settings.ANDROID_APP_LINK_SHA256_FINGERPRINTS
        )
    )
    valid = bool(certificates) and all(_CERTIFICATE.fullmatch(value) for value in certificates)
    associations = (
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": ANDROID_PACKAGE,
                    "sha256_cert_fingerprints": certificates,
                },
            }
        ]
        if valid
        else []
    )
    response = JsonResponse(associations, safe=False, status=200 if valid else 503, charset="utf-8")
    response["Cache-Control"] = "public, max-age=300" if valid else "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    if request.method == "HEAD":
        response.content = b""
    return response
