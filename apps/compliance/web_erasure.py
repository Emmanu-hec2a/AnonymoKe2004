"""Browser erasure challenges and a durable outbox. No sign-in tokens are issued."""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import RefreshSession, User
from apps.core.crypto import decrypt_text, encrypt_text

from .models import DataSubjectRequest, WebDeletionRequest
from .services import purge_user_data

logger = logging.getLogger("anonymoke.compliance")
TOKEN_TTL = timedelta(minutes=10)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def allow_request(email, ip):
    # Apply the same limits to existing and unknown email addresses.
    for label, value, maximum in [("ip", ip, 30), ("email", email, 5)]:
        key = f"web-erasure:{label}:{digest(value)}:{int(timezone.now().timestamp()) // 3600}"
        cache.add(key, 0, timeout=3600)
        if cache.incr(key) > maximum:
            return False
    return cache.add(f"web-erasure:cooldown:{digest(email)}", 1, timeout=60)


@transaction.atomic
def request_deletion(email):
    user = User.objects.select_for_update().filter(email__iexact=email).first()
    if not user or user.status == User.Status.DELETION_PENDING:
        return
    now = timezone.now()
    WebDeletionRequest.objects.filter(user=user, confirmed_at__isnull=True).update(
        expires_at=now, token_ciphertext=b""
    )
    token = secrets.token_urlsafe(32)
    WebDeletionRequest.objects.create(
        user=user,
        token_hash=digest(token),
        token_ciphertext=encrypt_text(token),
        expires_at=now + TOKEN_TTL,
    )
    # Beat dispatches this durable row. Keep broker latency and account-specific
    # email work out of the public request's response path.


def enqueue(job_id):
    from .tasks import process_web_deletion

    try:
        process_web_deletion.delay(str(job_id))
    except Exception:  # noqa: BLE001 - beat will recover the durable row
        logger.warning("web_erasure_dispatch_deferred")


@transaction.atomic
def confirm_deletion(token):
    token_hash = digest(token)
    lookup = WebDeletionRequest.objects.filter(token_hash=token_hash).first()
    if not lookup or not lookup.user_id:
        raise ValueError("link_invalid")
    # Match the account-lock order used by in-app erasure and request creation.
    user = User.objects.select_for_update().filter(pk=lookup.user_id).first()
    job = WebDeletionRequest.objects.select_for_update().get(pk=lookup.pk)
    if job.confirmed_at:
        return  # Repeated POSTs cannot create another deletion job.
    if not user or job.expires_at <= timezone.now():
        raise ValueError("link_invalid")
    job.confirmed_at = timezone.now()
    job.token_ciphertext = b""
    job.status = "confirmed"
    job.attempts = 0
    job.error_code = ""
    job.lease_until = None
    job.next_attempt_at = timezone.now()
    job.subject_request = DataSubjectRequest.objects.create(
        user=user,
        kind="erasure",
        status="processing",
        due_at=timezone.now() + timedelta(days=30),
        completion_proof={"source": "web"},
    )
    job.save()
    user.status = User.Status.DELETION_PENDING
    user.save(update_fields=["status"])
    RefreshSession.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def process(job_id):
    now = timezone.now()
    with transaction.atomic():
        job = WebDeletionRequest.objects.select_for_update().filter(pk=job_id).first()
        if not job or job.status in {"completed", "failed", "sent"}:
            return
        if job.next_attempt_at > now or (job.lease_until and job.lease_until > now):
            return
        deleting = job.confirmed_at is not None
        if not deleting and (job.expires_at <= now or not job.user_id):
            job.token_ciphertext = b""
            job.status = "failed"
            job.save(update_fields=["token_ciphertext", "status"])
            return
        job.lease_until = now + timedelta(minutes=2)
        if deleting:
            job.status = "processing"
        job.save(update_fields=["lease_until", "status"])
        lease = job.lease_until
    result = None
    try:
        if deleting:
            if job.user_id:
                try:
                    result = purge_user_data(str(job.user_id))
                except User.DoesNotExist:
                    pass  # Another authorized erasure already removed the account.
        else:
            from apps.accounts.mail import ResendEmailAdapter

            user = User.objects.filter(pk=job.user_id).first()
            if not user:
                raise ValueError("account_unavailable")
            ResendEmailAdapter().send_account_deletion(
                user.email, decrypt_text(bytes(job.token_ciphertext)), str(job.pk)
            )
    except Exception:  # noqa: BLE001 - never log addresses, URLs, tokens or provider responses
        with transaction.atomic():
            current = WebDeletionRequest.objects.select_for_update().get(pk=job.pk)
            if current.lease_until != lease or current.confirmed_at != job.confirmed_at:
                return
            current.attempts += 1
            current.lease_until = None
            current.error_code = (
                "storage_temporarily_unavailable" if deleting else "email_unavailable"
            )
            current.status = (
                "confirmed" if deleting else ("failed" if current.attempts >= 5 else "pending")
            )
            current.next_attempt_at = timezone.now() + timedelta(
                seconds=min(15 * 2 ** min(current.attempts, 6), 900)
            )
            if current.status == "failed":
                current.token_ciphertext = b""
            current.save()
        logger.warning("web_erasure_attempt_deferred phase=%s", "purge" if deleting else "email")
        return
    with transaction.atomic():
        current = WebDeletionRequest.objects.select_for_update().get(pk=job.pk)
        if current.lease_until != lease or current.confirmed_at != job.confirmed_at:
            return
        current.lease_until = None
        current.token_ciphertext = b""
        current.error_code = ""
        current.status = "completed" if deleting else "sent"
        if deleting:
            current.completed_at = timezone.now()
            DataSubjectRequest.objects.filter(pk=current.subject_request_id).update(
                status="completed",
                completed_at=current.completed_at,
                completion_proof={
                    "source": "web",
                    "deleted_objects": result.deleted_objects
                    if result
                    else ["user_already_removed"],
                    "retained_financial_transactions": result.retained_financial_transactions
                    if result
                    else 0,
                },
            )
        current.save()


def recover():
    now = timezone.now()
    query = (
        WebDeletionRequest.objects.filter(
            Q(status="pending", expires_at__gt=now) | Q(status__in=["confirmed", "processing"]),
            next_attempt_at__lte=now,
        )
        .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
        .order_by("next_attempt_at")
    )
    for pk in query.values_list("pk", flat=True)[:100]:
        enqueue(pk)
    # Verification material is short-lived, while the minimal erasure audit remains.
    WebDeletionRequest.objects.filter(confirmed_at__isnull=True, expires_at__lte=now).update(
        token_ciphertext=b""
    )
    WebDeletionRequest.objects.filter(
        Q(confirmed_at__isnull=True, expires_at__lt=now - timedelta(days=1))
        | Q(status="completed", completed_at__lt=now - timedelta(days=1))
    ).delete()
