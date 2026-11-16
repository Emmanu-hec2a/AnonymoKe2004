from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .lifecycle import lock_owner, queue_delivery
from .models import DateSession


def process_due_checkins():
    now = timezone.now()
    ids = list(
        DateSession.objects.filter(
            status="active", check_in_due_at__lte=now + timedelta(minutes=15)
        )
        .filter(
            Q(check_in_due_at__lt=now - timedelta(hours=24))
            | Q(overdue_at__isnull=True, check_in_due_at__lte=now - timedelta(minutes=15))
            | Q(reminder_sent_at__isnull=True, check_in_due_at__gt=now - timedelta(minutes=15))
        )
        .order_by("check_in_due_at")
        .values_list("pk", "user_id")[:500]
    )
    processed = 0
    for session_id, user_id in ids:
        with transaction.atomic():
            try:
                lock_owner(user_id)
            except ValueError:
                continue
            session = DateSession.objects.select_for_update().get(pk=session_id)
            if session.status != "active" or session.check_in_due_at > now + timedelta(minutes=15):
                continue
            if session.check_in_due_at < now - timedelta(hours=24):
                session.status = "expired"
                if session.trusted_contact_user_id:
                    queue_delivery(
                        session,
                        session.trusted_contact_user_id,
                        "safety.expired",
                        f"expired:{session.pk}",
                    )
            elif session.check_in_due_at <= now - timedelta(minutes=15):
                if not session.overdue_at:
                    session.overdue_at = now
                    if session.trusted_contact_user_id:
                        queue_delivery(
                            session,
                            session.trusted_contact_user_id,
                            "safety.overdue",
                            f"overdue:{session.pk}:{session.check_in_due_at.isoformat()}",
                        )
            elif not session.reminder_sent_at:
                session.reminder_sent_at = now
                queue_delivery(
                    session,
                    user_id,
                    "safety.checkin_due",
                    f"reminder:{session.pk}:{session.check_in_due_at.isoformat()}",
                )
            session.save(update_fields=["status", "reminder_sent_at", "overdue_at", "updated_at"])
            processed += 1
    return processed


def purge_old_plans():
    cutoff = timezone.now() - timedelta(days=settings.SAFETY_RETENTION_DAYS)
    return DateSession.objects.filter(
        status__in=["safe", "cancelled", "expired"], updated_at__lt=cutoff
    ).delete()[0]
