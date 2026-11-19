import json
import logging
from dataclasses import dataclass

from django.conf import settings

from .models import DeviceToken

logger = logging.getLogger("anonymoke.notifications")


@dataclass(frozen=True)
class PushResult:
    accepted: int = 0
    unavailable_reason: str = ""


def _skipped(event_type: str, user_id, reason: str) -> PushResult:
    # Surface why a push was not attempted; callers otherwise only see a status string.
    logger.info("push_skipped event=%s user=%s reason=%s", event_type, user_id, reason)
    return PushResult(unavailable_reason=reason)


def _firebase_app():
    if not settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        return None
    import firebase_admin
    from firebase_admin import credentials

    try:
        return firebase_admin.get_app()
    except ValueError:
        info = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        return firebase_admin.initialize_app(
            credentials.Certificate(info),
            {"projectId": settings.FIREBASE_PROJECT_ID or info.get("project_id")},
        )


def _content(event_type: str, actor_alias: str | None) -> tuple[str, str]:
    name = actor_alias or "Someone"
    return {
        "like.received": ("Someone likes you", "Someone new likes your profile."),
        "match.created": ("New match", "You have a new match. Say hello when you're ready."),
        "chat.message": ("New message", f"{name} sent you a message."),
        "reveal.requested": ("Reveal request", f"{name} is ready to reveal."),
        "reveal.accepted": ("Mutual reveal", "Your mutual reveal is ready."),
        "reveal.declined": ("Reveal update", f"{name} declined the reveal for now."),
        "reveal.withdrawn": ("Reveal update", "The reveal request has been withdrawn."),
        "match.closed": ("Conversation update", "A conversation has closed."),
        "safety.panic": ("Safety alert", f"{name} has triggered a safety alert. Please check in."),
        "safety.plan_shared": ("Shared date plan", f"{name} shared a date plan with you."),
        "safety.plan_updated": ("Date plan updated", "Open Safety to see the updated plan."),
        "safety.safe": ("Safe check-in", f"{name} has marked themselves safe."),
        "safety.cancelled": ("Date plan cancelled", "A shared date plan was cancelled."),
        "safety.expired": ("Date plan ended", "A date plan has expired without a safe check-in."),
        "safety.checkin_due": (
            "Check-in reminder",
            "Open Safety to check in or update your deadline.",
        ),
        "safety.overdue": (
            "Missed check-in",
            f"{name} missed a check-in. Please check on them; this is not a confirmed emergency.",
        ),
        "safety.acknowledged": (
            "Contact acknowledged",
            "Your trusted contact acknowledged your alert.",
        ),
    }.get(event_type, ("AnonymoKE update", "You have a new update."))


def send_user_event(
    *,
    user_id,
    event_type: str,
    match_id: str | None = None,
    actor_alias: str | None = None,
) -> PushResult:
    # Queued pushes may outlive the relationship that created them.
    if match_id and event_type != "match.closed":
        from apps.matching.services import participant_match
        from apps.profiles.models import Profile

        profile = Profile.objects.filter(user_id=user_id).first()
        if not profile:
            return _skipped(event_type, user_id, "relationship_unavailable")
        try:
            participant_match(profile, match_id)
        except ValueError:
            return _skipped(event_type, user_id, "relationship_unavailable")
    app = _firebase_app()
    if app is None:
        logger.info("firebase_notifications_disabled", extra={"event_type": event_type})
        return _skipped(event_type, user_id, "push_unconfigured")

    import firebase_admin.messaging as messaging

    devices = list(DeviceToken.objects.filter(user_id=user_id, is_enabled=True))
    if not devices:
        return _skipped(event_type, user_id, "no_registered_device")
    title, body = _content(event_type, actor_alias)
    data = {"type": event_type}
    if match_id:
        data["match_id"] = str(match_id)
    invalid_tokens = []
    accepted = 0
    transient_failure = False
    for start in range(0, len(devices), 500):
        batch = devices[start : start + 500]
        message = messaging.MulticastMessage(
            tokens=[device.token for device in batch],
            notification=messaging.Notification(title=title, body=body),
            data=data,
            android=messaging.AndroidConfig(priority="high"),
            apns=messaging.APNSConfig(
                headers={"apns-priority": "10"},
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1),
                ),
            ),
        )
        response = messaging.send_each_for_multicast(message, app=app)
        for device, result in zip(batch, response.responses, strict=False):
            if result.success:
                accepted += 1
                continue
            error = str(result.exception).lower()
            logger.warning(
                "push_send_failed event=%s error_type=%s",
                event_type,
                type(result.exception).__name__,
            )
            if "unregistered" in error or "invalid" in error:
                invalid_tokens.append(device.token)
            else:
                transient_failure = True
    if invalid_tokens:
        DeviceToken.objects.filter(token__in=invalid_tokens).update(is_enabled=False)
    logger.info(
        "push_delivery_result event=%s user=%s devices=%d accepted=%d invalid_tokens=%d",
        event_type,
        user_id,
        len(devices),
        accepted,
        len(invalid_tokens),
    )
    if accepted == 0 and transient_failure:
        raise RuntimeError("push_temporarily_unavailable")
    return PushResult(
        accepted=accepted, unavailable_reason="" if accepted else "no_registered_device"
    )


def enqueue_user_event(
    *,
    user_id,
    event_type: str,
    match_id: str | None = None,
    actor_alias: str | None = None,
) -> None:
    from .tasks import deliver_user_event

    deliver_user_event.delay(
        str(user_id),
        event_type,
        match_id=match_id,
        actor_alias=actor_alias,
    )
