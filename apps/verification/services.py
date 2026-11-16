import hashlib
import hmac
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.compliance.consent import has_active_consent
from apps.compliance.models import AuditLog
from apps.core.crypto import decrypt_text, encrypt_text
from apps.profiles.models import Profile

from .models import VerificationAttempt
from .smile import SmileID, configured


@dataclass(frozen=True)
class VerificationStart:
    attempt: VerificationAttempt
    launch_url: str | None = None


def reference_hash(reference):
    return hmac.new(settings.JWT_SECRET.encode(), reference.encode(), hashlib.sha256).hexdigest()


def verification_available():
    return (
        settings.VERIFICATION_PROVIDER == "smile_id"
        and configured()
        and settings.SMILE_ID_ADULT_POLICY_CONFIRMED
    )


class VerificationService:
    @staticmethod
    def start(user, purpose):
        if purpose not in {"age_check", "identity_check"}:
            raise ValueError("verification_purpose_invalid")
        if not verification_available():
            raise RuntimeError("verification_provider_unavailable")
        if not has_active_consent(user, "sensitive_data"):
            raise ValueError("sensitive_data_consent_required")
        with transaction.atomic():
            type(user).objects.select_for_update().get(pk=user.pk)
            existing = (
                VerificationAttempt.objects.filter(user=user, status="pending", provider="smile_id")
                .order_by("-created_at")
                .first()
            )
            if existing and existing.expires_at and existing.expires_at > timezone.now():
                return VerificationStart(
                    existing, decrypt_text(bytes(existing.launch_url_ciphertext))
                )
            if (
                existing
                and not existing.expires_at
                and (timezone.now() - existing.created_at).total_seconds() < 60
            ):
                raise ValueError("verification_start_in_progress")
            attempt = VerificationAttempt.objects.create(
                user=user, provider="smile_id", purpose=purpose
            )
            AuditLog.objects.create(
                actor_user_id=user.pk,
                action="verification.consent_granted",
                object_type="VerificationAttempt",
                object_id=attempt.pk,
                metadata={
                    "notice_url": settings.SMILE_ID_PRIVACY_URL,
                    "version": "verification-v1",
                },
            )
        try:
            reference, url, expires = SmileID().create_session(str(attempt.pk))
        except RuntimeError:
            VerificationAttempt.objects.filter(pk=attempt.pk).update(
                status="failed", reason_code="provider_unavailable"
            )
            raise
        attempt.provider_reference_hash = reference_hash(reference)
        attempt.launch_url_ciphertext = encrypt_text(url)
        attempt.expires_at = expires
        attempt.save(
            update_fields=[
                "provider_reference_hash",
                "launch_url_ciphertext",
                "expires_at",
                "updated_at",
            ]
        )
        return VerificationStart(attempt, url)


def reconcile_attempt(attempt_id, *, job_id=None):
    attempt = (
        VerificationAttempt.objects.select_related("user")
        .filter(pk=attempt_id, provider="smile_id")
        .first()
    )
    if (
        not attempt
        or not (job_id or attempt.provider_job_id)
        or attempt.status in {"passed", "failed"}
    ):
        return
    job_id = job_id or attempt.provider_job_id
    result = SmileID().result(str(attempt.pk), job_id)
    if result.get("user_id") != str(attempt.pk) or result.get("job_id") != job_id:
        raise ValueError("verification_reference_mismatch")
    outcome = result.get("status")
    if outcome not in {"clear", "block", "attention", "error", "processing"}:
        raise ValueError("verification_status_invalid")
    with transaction.atomic():
        user = type(attempt.user).objects.select_for_update().get(pk=attempt.user_id)
        current = VerificationAttempt.objects.select_for_update().get(pk=attempt.pk)
        if current.status in {"passed", "failed"}:
            return
        current.last_synced_at = timezone.now()
        if current.provider_job_id and current.provider_job_id != job_id:
            raise ValueError("verification_reference_mismatch")
        current.provider_job_id = job_id
        if outcome == "clear":
            if not verification_available() or (
                not settings.DEBUG and settings.SMILE_ID_ENVIRONMENT != "production"
            ):
                raise ValueError("verification_environment_invalid")
            if user.status != "active" or not has_active_consent(user, "sensitive_data"):
                raise ValueError("sensitive_data_consent_required")
            current.status = "passed"
            profile, _ = Profile.objects.get_or_create(user=attempt.user)
            profile.verification_level = "verified"
            profile.save(update_fields=["verification_level", "updated_at"])
        elif outcome in {"block", "error"}:
            current.status = "failed"
            current.reason_code = "verification_failed" if outcome == "block" else "provider_error"
        elif outcome == "attention":
            current.status = "review"
            current.reason_code = "provider_review_required"
        current.save(
            update_fields=[
                "status",
                "reason_code",
                "last_synced_at",
                "provider_job_id",
                "updated_at",
            ]
        )
        if current.status in {"passed", "failed"}:
            current.launch_url_ciphertext = b""
            current.save(update_fields=["launch_url_ciphertext"])
        AuditLog.objects.create(
            actor_user_id=attempt.user_id,
            action="verification.result_checked",
            object_type="VerificationAttempt",
            object_id=attempt.pk,
            metadata={"status": current.status},
        )


def valid_webhook_signature(body, signature):
    # Legacy callbacks cannot update Smile ID attempts.
    if not settings.DEBUG or not settings.VERIFICATION_WEBHOOK_SECRET or not signature:
        return False
    expected = hmac.new(
        settings.VERIFICATION_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)
