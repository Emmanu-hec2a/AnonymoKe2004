import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.compliance.consent import has_active_consent
from apps.compliance.models import AuditLog
from apps.profiles.models import Profile

from .models import DateSession, PanicAlert, SafetyAlertRecipient, SafetyDelivery, TrustedContact

OPEN_STATES = ("active", "panic")
logger = logging.getLogger("anonymoke.safety")


def lock_owner(user_id):
    user = User.objects.select_for_update().filter(pk=user_id, status="active").first()
    if not user:
        raise ValueError("account_not_active")
    return user


def invite_hash(code):
    return hmac.new(settings.JWT_SECRET.encode(), code.encode(), hashlib.sha256).hexdigest()


def queue_delivery(session, recipient_id, event_type, key, alert=None):
    delivery, created = SafetyDelivery.objects.get_or_create(
        dedupe_key=key,
        defaults={
            "session": session,
            "recipient_id": recipient_id,
            "event_type": event_type,
            "alert": alert,
        },
    )
    if created:

        def dispatch():
            from .tasks import dispatch_safety_delivery

            try:
                dispatch_safety_delivery.delay(str(delivery.pk))
            except Exception:  # noqa: BLE001 - beat recovers the durable outbox
                logger.warning("safety_delivery_pending_broker_recovery")

        transaction.on_commit(dispatch)
    return delivery


def trusted_contact(user, *, lock=False):
    query = TrustedContact.objects.select_related("linked_user__profile")
    if lock:
        query = query.select_for_update(of=("self",))
    return query.filter(user=user).first()


def linked_contact(user):
    contact = trusted_contact(user, lock=True)
    if not contact:
        raise ValueError("trusted_contact_required")
    if not contact.linked_user_id or contact.linked_user.status != "active":
        raise ValueError("trusted_contact_not_linked")
    return contact


@transaction.atomic
def issue_invite(user):
    lock_owner(user.pk)
    contact = trusted_contact(user, lock=True)
    if not contact:
        raise ValueError("trusted_contact_required")
    if contact.linked_user_id:
        raise ValueError("trusted_contact_already_linked")
    code = secrets.token_hex(6).upper()
    contact.invite_code_hash = invite_hash(code)
    contact.invite_expires_at = timezone.now() + timedelta(hours=24)
    contact.save(update_fields=["invite_code_hash", "invite_expires_at", "updated_at"])
    return code, contact.invite_expires_at


@transaction.atomic
def accept_invite(user, code):
    code = str(code).strip().replace(" ", "").upper()
    if len(code) not in (8, 12) or any(c not in "0123456789ABCDEF" for c in code):
        raise ValueError("invite_code_invalid")
    candidate = TrustedContact.objects.filter(invite_code_hash=invite_hash(code)).first()
    if not candidate or candidate.user_id == user.pk:
        raise ValueError("invite_code_expired_or_invalid")
    lock_owner(candidate.user_id)
    contact = (
        TrustedContact.objects.select_for_update()
        .filter(
            pk=candidate.pk,
            invite_code_hash=invite_hash(code),
            invite_expires_at__gt=timezone.now(),
            linked_user__isnull=True,
        )
        .first()
    )
    if not contact or not User.objects.filter(pk=user.pk, status="active").exists():
        raise ValueError("invite_code_expired_or_invalid")
    contact.linked_user = user
    contact.invite_code_hash = ""
    contact.invite_expires_at = None
    contact.save(
        update_fields=["linked_user", "invite_code_hash", "invite_expires_at", "updated_at"]
    )
    return contact


@transaction.atomic
def unlink_contact(user):
    lock_owner(user.pk)
    if DateSession.objects.filter(user=user, status__in=OPEN_STATES).exists():
        raise ValueError("resolve_date_before_unlink")
    contact = trusted_contact(user, lock=True)
    if contact:
        contact.linked_user = None
        contact.invite_code_hash = ""
        contact.invite_expires_at = None
        contact.save(
            update_fields=["linked_user", "invite_code_hash", "invite_expires_at", "updated_at"]
        )


def approximate_area(user):
    if not has_active_consent(user, "location"):
        raise ValueError("location_consent_required")
    profile = Profile.objects.filter(
        user=user, location_flagged=False, cell_updated_at__gte=timezone.now() - timedelta(days=7)
    ).first()
    if not profile or not profile.cell:
        raise ValueError("location_required")
    return {
        "latitude": round(profile.cell.y, 1),
        "longitude": round(profile.cell.x, 1),
        "radius_km": 12,
    }


@transaction.atomic
def save_plan(user, data, session_id=None):
    lock_owner(user.pk)
    contact = linked_contact(user)
    if session_id:
        session = DateSession.objects.select_for_update().filter(pk=session_id, user=user).first()
        if not session or session.status != "active":
            raise ValueError("date_session_not_active")
        if session.trusted_contact_user_id != contact.linked_user_id:
            raise ValueError("trusted_contact_changed")
    else:
        if DateSession.objects.filter(user=user, status__in=OPEN_STATES).exists():
            raise ValueError("active_date_already_exists")
        session = DateSession(
            user=user,
            trusted_contact_user=contact.linked_user,
            trusted_contact_name=contact.contact_name,
        )
    from .serializers import DateSessionWriteSerializer

    # Revalidate partial edits against the locked, current plan, not a stale view instance.
    serializer = DateSessionWriteSerializer(
        session if session_id else None, data=data, partial=bool(session_id)
    )
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    changed_due = "check_in_due_at" in data and data["check_in_due_at"] != session.check_in_due_at
    for key, value in data.items():
        setattr(session, key, value)
    session.approximate_area = (
        approximate_area(user) if session.share_approximate_location else None
    )
    if changed_due:
        session.reminder_sent_at = None
        session.overdue_at = None
    session.save()
    queue_delivery(
        session,
        session.trusted_contact_user_id,
        "safety.plan_shared" if not session_id else "safety.plan_updated",
        f"plan:{session.pk}:{session.updated_at.isoformat()}",
    )
    return session


@transaction.atomic
def resolve_plan(user, session_id, *, safe):
    lock_owner(user.pk)
    session = DateSession.objects.select_for_update().filter(pk=session_id, user=user).first()
    if not session:
        raise ValueError("date_session_not_found")
    target = "safe" if safe else "cancelled"
    if session.status == target:
        return session
    if session.status not in OPEN_STATES:
        raise ValueError("date_session_not_active")
    if not safe and session.status == "panic":
        raise ValueError("mark_safe_to_resolve_panic")
    session.status = target
    if safe:
        session.safe_at = timezone.now()
    session.save(update_fields=["status", "safe_at", "updated_at"])
    if session.trusted_contact_user_id:
        queue_delivery(
            session,
            session.trusted_contact_user_id,
            f"safety.{target}",
            f"resolved:{session.pk}:{target}",
        )
    AuditLog.objects.create(
        actor_user_id=user.pk,
        action=f"safety.date_{target}",
        object_type="DateSession",
        object_id=session.pk,
    )
    return session


@transaction.atomic
def trigger_panic(user, key):
    lock_owner(user.pk)
    existing = PanicAlert.objects.filter(user=user, idempotency_key=key).first()
    if existing:
        return existing, False
    session = (
        DateSession.objects.select_for_update().filter(user=user, status__in=OPEN_STATES).first()
    )
    if not session:
        raise ValueError("active_date_required")
    contact = linked_contact(user)
    if session.trusted_contact_user_id != contact.linked_user_id:
        raise ValueError("trusted_contact_changed")
    # A second tap or an ambiguous first response reuses the same session alert.
    existing = PanicAlert.objects.filter(date_session=session).order_by("triggered_at").first()
    if existing:
        return existing, False
    if (
        PanicAlert.objects.filter(
            user=user, triggered_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
        >= 5
    ):
        raise ValueError("panic_rate_limited")
    session.status = "panic"
    session.panic_at = timezone.now()
    session.save(update_fields=["status", "panic_at", "updated_at"])
    alert = PanicAlert.objects.create(
        user=user, date_session=session, idempotency_key=key, status="stored"
    )
    SafetyAlertRecipient.objects.create(
        alert=alert, recipient_user_id=session.trusted_contact_user_id
    )
    queue_delivery(
        session, session.trusted_contact_user_id, "safety.panic", f"panic:{alert.pk}", alert
    )
    AuditLog.objects.create(
        actor_user_id=user.pk,
        action="safety.panic_triggered",
        object_type="PanicAlert",
        object_id=alert.pk,
    )
    return alert, True


@transaction.atomic
def acknowledge_alert(user, recipient_id):
    candidate = (
        SafetyAlertRecipient.objects.select_related("alert")
        .filter(pk=recipient_id, recipient_user=user)
        .first()
    )
    if not candidate:
        raise ValueError("safety_alert_not_found")
    lock_owner(candidate.alert.user_id)
    recipient = (
        SafetyAlertRecipient.objects.select_for_update()
        .select_related("alert__date_session")
        .get(pk=candidate.pk)
    )
    if not TrustedContact.objects.filter(
        user_id=recipient.alert.user_id, linked_user=user
    ).exists():
        raise ValueError("safety_alert_not_found")
    if recipient.status != "acknowledged":
        recipient.status = "acknowledged"
        recipient.acknowledged_at = timezone.now()
        recipient.save(update_fields=["status", "acknowledged_at"])
        PanicAlert.objects.filter(pk=recipient.alert_id).update(
            status="acknowledged", delivered_at=recipient.acknowledged_at
        )
        queue_delivery(
            recipient.alert.date_session,
            recipient.alert.user_id,
            "safety.acknowledged",
            f"ack:{recipient.pk}",
        )
    return recipient
