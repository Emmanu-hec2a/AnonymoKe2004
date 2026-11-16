import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from .models import VerificationAttempt, VerificationResultCheck
from .services import reconcile_attempt


@shared_task(queue="moderation")
def check_verification_result(check_id):
    now = timezone.now()
    claimed = VerificationResultCheck.objects.filter(
        pk=check_id, completed_at__isnull=True, next_attempt_at__lte=now
    ).update(next_attempt_at=now + timedelta(seconds=90))
    if not claimed:
        return
    check = VerificationResultCheck.objects.filter(pk=check_id).first()
    if not check:
        return
    try:
        reconcile_attempt(check.attempt_id, job_id=check.job_id)
    except RuntimeError:
        # The hint survives broker/provider outages; beat retries for up to 24 hours.
        check.attempts += 1
        check.next_attempt_at = timezone.now() + timedelta(
            seconds=min(30 * 2 ** min(check.attempts, 6), 1800)
        )
        if check.created_at < timezone.now() - timedelta(hours=24):
            check.completed_at = timezone.now()
        check.save(update_fields=["attempts", "next_attempt_at", "completed_at"])
        return
    except ValueError:
        # A mismatched hint never reserves the attempt's authoritative job ID.
        pass
    check.completed_at = timezone.now()
    check.save(update_fields=["completed_at"])


@shared_task(queue="moderation")
def refresh_verification_attempt(attempt_id):
    now = timezone.now()
    claimed = (
        VerificationAttempt.objects.filter(pk=attempt_id, status__in=["pending", "review"])
        .filter(Q(last_synced_at__isnull=True) | Q(last_synced_at__lt=now - timedelta(minutes=2)))
        .update(last_synced_at=now)
    )
    if claimed:
        try:
            reconcile_attempt(attempt_id)
        except (RuntimeError, ValueError):
            pass  # Periodic reconciliation retries without keeping a worker occupied in a loop.


@shared_task(queue="moderation")
def reconcile_verifications():
    now = timezone.now()
    for check_id in VerificationResultCheck.objects.filter(
        completed_at__isnull=True, next_attempt_at__lte=now
    ).values_list("pk", flat=True)[:100]:
        try:
            check_verification_result.delay(check_id)
        except Exception:  # noqa: BLE001 - persistent checks remain eligible for the next beat
            logging.getLogger("anonymoke.verification").warning("verification_broker_unavailable")
            break
    query = (
        VerificationAttempt.objects.filter(provider="smile_id", status__in=["pending", "review"])
        .exclude(provider_job_id="")
        .filter(Q(last_synced_at__isnull=True) | Q(last_synced_at__lt=now - timedelta(minutes=2)))
    )
    count = 0
    for attempt in query.order_by("last_synced_at")[:50]:
        try:
            refresh_verification_attempt.delay(str(attempt.pk))
        except Exception:  # noqa: BLE001 - the next beat retries
            break
        count += 1
    VerificationAttempt.objects.filter(
        status="pending", provider_job_id="", expires_at__lt=now
    ).exclude(
        verificationresultcheck__completed_at__isnull=True,
        verificationresultcheck__pk__isnull=False,
    ).update(status="failed", reason_code="session_expired", launch_url_ciphertext=b"")
    VerificationAttempt.objects.filter(created_at__lt=now - timedelta(days=30)).delete()
    return count
