import re
import secrets
from functools import lru_cache
from importlib.resources import files

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_safe

from .web_erasure import allow_request, confirm_deletion, request_deletion


def page(request, template, context=None, status=200, private=False):
    nonce = secrets.token_urlsafe(24)
    response = render(request, template, {**(context or {}), "nonce": nonce}, status=status)
    response["Cache-Control"] = "no-store" if private else "public, max-age=300"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    if private:
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@lru_cache(maxsize=2)
def document(kind):
    name = "privacy-policy.txt" if kind == "privacy" else "terms-of-use.txt"
    text = files("apps.compliance").joinpath("resources", name).read_text(encoding="utf-8")
    lines = [line.strip().replace("\u200b", "") for line in text.splitlines()]
    blocks = []
    section = 1
    for line in lines[2:]:
        if not line:
            continue
        heading = re.fullmatch(r"(\d+)\.\s+[^:]+", line)
        is_section = bool(heading and int(heading[1]) == section)
        if is_section:
            section += 1
        blocks.append({"text": line, "heading": is_section})
    return {"title": lines[0], "official_title": lines[1], "blocks": blocks}


@require_safe
def privacy_policy(request):
    return page(request, "compliance/document.html", document("privacy"))


@require_safe
def terms(request):
    return page(request, "compliance/document.html", document("terms"))


@require_safe
def logo(request):
    response = HttpResponse(
        files("apps.accounts").joinpath("resources", "anonymoke-logo.jpeg").read_bytes(),
        content_type="image/jpeg",
    )
    response["Cache-Control"] = "public, max-age=86400"
    return response


@require_http_methods(["GET", "HEAD", "POST"])
@sensitive_post_parameters("email")
def deletion_request(request):
    context = {"title": "Delete your AnonymoKe account"}
    status = 200
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        try:
            validate_email(email)
            if len(email) > 254:
                raise ValidationError("email_invalid")
        except ValidationError:
            context["error"] = "Enter a valid email address."
            status = 400
        else:
            try:
                # REMOTE_ADDR is the trusted proxy connection; do not trust arbitrary
                # X-Forwarded-For headers for abuse limits.
                if allow_request(email, request.META.get("REMOTE_ADDR", "unknown")):
                    request_deletion(email)
                context["requested"] = True
            except Exception:  # noqa: BLE001 - same response for all addresses
                context["error"] = (
                    "We could not accept requests right now. Please try again shortly."
                )
                status = 503
    return page(request, "compliance/deletion.html", context, status, private=True)


@require_safe
def deletion_verify(request):
    return page(
        request, "compliance/confirm.html", {"title": "Confirm account deletion"}, private=True
    )


@require_http_methods(["POST"])
@sensitive_post_parameters("token")
def deletion_confirm(request):
    token = request.POST.get("token", "")
    if request.POST.get("confirm") != "yes" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return page(
            request,
            "compliance/result.html",
            {"title": "Unable to confirm deletion", "invalid": True},
            400,
            private=True,
        )
    try:
        confirm_deletion(token)
    except ValueError:
        return page(
            request,
            "compliance/result.html",
            {"title": "This link is no longer valid", "invalid": True},
            400,
            private=True,
        )
    return page(
        request, "compliance/result.html", {"title": "Deletion request confirmed"}, private=True
    )
