import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.notifications.service import send_user_event

from .models import PanicAlert, SafetyDelivery, TrustedContact

logger = logging.getLogger("anonymoke.safety")


def process_delivery(delivery_id):
    now = timezone.now()
    with transaction.atomic():
        job = (
            SafetyDelivery.objects.select_for_update(of=("self",))
            .select_related("session__user__profile", "recipient")
            .filter(pk=delivery_id)
            .first()
        )
        if not job or job.status in {"push_accepted", "cancelled", "failed"}:
            return "ignored"
        if job.next_attempt_at > now or (job.lease_until and job.lease_until > now):
            return "pending"
        session = job.session
        owner = session.user
        if owner.status != "active" or job.recipient.status != "active":
            job.status = "cancelled"
        elif (
            job.recipient_id != owner.pk
            and not TrustedContact.objects.filter(
                user=owner, linked_user_id=job.recipient_id
            ).exists()
        ):
            job.status = "cancelled"
        elif job.event_type in {
            "safety.panic",
            "safety.overdue",
            "safety.checkin_due",
        } and session.status not in {"active", "panic"}:
            job.status = "cancelled"
        elif job.event_type in {
            "safety.overdue",
            "safety.checkin_due",
        } and not job.dedupe_key.endswith(f":{session.check_in_due_at.isoformat()}"):
            # Editing the deadline invalidates any old reminder still in the outbox.
            job.status = "cancelled"
        elif job.created_at < now - timedelta(hours=24):
            job.status = "cancelled"
        if job.status == "cancelled":
            job.save(update_fields=["status", "updated_at"])
            return "cancelled"
        job.status = "processing"
        job.lease_until = now + timedelta(seconds=90)
        job.save(update_fields=["status", "lease_until", "updated_at"])
    try:
        result = send_user_event(
            user_id=job.recipient_id,
            event_type=job.event_type,
            actor_alias=getattr(getattr(owner, "profile", None), "alias", None),
        )
        accepted = result is not None and result.accepted > 0
        error = "" if accepted else getattr(result, "unavailable_reason", "push_unavailable")
    except Exception:  # noqa: BLE001 - retry state is durable and sanitized
        accepted = False
        error = "push_temporarily_unavailable"
    with transaction.atomic():
        current = SafetyDelivery.objects.select_for_update().get(pk=delivery_id)
        # A user-requested retry cannot overwrite an active lease.
        if current.status != "processing" or current.lease_until != job.lease_until:
            return current.status
        current.lease_until = None
        current.error_code = error
        if accepted:
            current.status = "push_accepted"
            current.accepted_at = timezone.now()
            if current.alert_id:
                PanicAlert.objects.filter(pk=current.alert_id).exclude(
                    status="acknowledged"
                ).update(status="push_accepted")
        elif error == "push_temporarily_unavailable":
            current.attempts += 1
            current.status = "failed" if current.attempts >= 8 else "queued"
            current.next_attempt_at = timezone.now() + timedelta(
                seconds=min(15 * 2**current.attempts, 900)
            )
        else:
            current.status = "unavailable"
            current.next_attempt_at = timezone.now() + timedelta(minutes=15)
        current.save(
            update_fields=[
                "status",
                "attempts",
                "error_code",
                "lease_until",
                "accepted_at",
                "next_attempt_at",
                "updated_at",
            ]
        )
        return current.status


def dispatch_pending():
    from .tasks import dispatch_safety_delivery

    now = timezone.now()
    query = (
        SafetyDelivery.objects.filter(
            status__in=["queued", "unavailable", "processing"], next_attempt_at__lte=now
        )
        .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
        .order_by("next_attempt_at")[:200]
    )
    count = 0
    for delivery_id in query.values_list("pk", flat=True):
        try:
            dispatch_safety_delivery.delay(str(delivery_id))
        except Exception:  # noqa: BLE001 - retain the outbox until broker recovery
            logger.warning("safety_outbox_broker_unavailable")
            break
        count += 1
    return count
