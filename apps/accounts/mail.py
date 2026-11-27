import base64
import json
import logging
from datetime import UTC, datetime
from importlib.resources import files
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger("anonymoke.accounts.email")


class EmailDeliveryProvider:
    def send_magic_link(self, email: str, token: str) -> str:
        raise NotImplementedError


class ResendEmailAdapter(EmailDeliveryProvider):
    def send_magic_link(self, email: str, token: str) -> str:
        if not settings.RESEND_API_KEY:
            raise RuntimeError("resend_not_configured")
        context = {
            "sign_in_url": f"{settings.MAGIC_LINK_BASE_URL}{quote(token, safe='')}",
            "ttl_minutes": settings.MAGIC_LINK_TTL_MINUTES,
            "year": datetime.now(UTC).year,
            "reply_to_email": settings.RESEND_REPLY_TO_EMAIL,
            "privacy_url": settings.EMAIL_PRIVACY_URL,
            "terms_url": settings.EMAIL_TERMS_URL,
        }
        logo = files("apps.accounts").joinpath("resources", "anonymoke-logo.jpeg").read_bytes()
        message = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [email],
            "subject": "Your AnonymoKE sign-in link",
            "html": render_to_string("accounts/emails/magic_link.html", context),
            "text": render_to_string("accounts/emails/magic_link.txt", context),
            "attachments": [
                {
                    "filename": "anonymoke-logo.jpeg",
                    "content": base64.b64encode(logo).decode("ascii"),
                    "content_type": "image/jpeg",
                    "content_id": "anonymoke-logo",
                }
            ],
        }
        if settings.RESEND_REPLY_TO_EMAIL:
            message["reply_to"] = settings.RESEND_REPLY_TO_EMAIL
        return self._deliver(message)

    def send_account_deletion(self, email: str, token: str, request_id: str) -> str:
        context = {
            "confirmation_url": (
                f"{settings.PUBLIC_BASE_URL}/delete-account/verify/#token={quote(token, safe='')}"
            ),
            "privacy_url": f"{settings.PUBLIC_BASE_URL}/privacy-policy/",
            "terms_url": f"{settings.PUBLIC_BASE_URL}/terms/",
        }
        message = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [email],
            "subject": "Confirm deletion of your AnonymoKe account",
            "html": render_to_string("accounts/emails/account_deletion.html", context),
            "text": render_to_string("accounts/emails/account_deletion.txt", context),
        }
        if settings.RESEND_REPLY_TO_EMAIL:
            message["reply_to"] = settings.RESEND_REPLY_TO_EMAIL
        return self._deliver(message, idempotency_key=f"account-deletion/{request_id}")

    def _deliver(self, message: dict, idempotency_key: str | None = None) -> str:
        if not settings.RESEND_API_KEY:
            raise RuntimeError("resend_not_configured")
        req = request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(message).encode(),
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "AnonymoKE/1.0 (+https://anonymoke.co.ke)",
                **({"Idempotency-Key": idempotency_key} if idempotency_key else {}),
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as response:  # noqa: S310 - fixed HTTPS Resend endpoint
                payload = json.loads(response.read())
            message_id = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(message_id, str) or not message_id.strip():
                raise ValueError("resend_invalid_response")
            return message_id
        except HTTPError as error:
            logger.warning("Resend rejected transactional email (http_status=%s).", error.code)
            raise
        except (URLError, TimeoutError) as error:
            logger.warning("Resend connection failed (error_type=%s).", type(error).__name__)
            raise
        except (ValueError, KeyError, TypeError) as error:
            logger.warning(
                "Resend returned an invalid response (error_type=%s).", type(error).__name__
            )
            raise
