import hashlib

from celery import shared_task

from .models import ModerationFlagRecord
from .moderation import scan_text


@shared_task(queue="moderation")
def scan_content(subject_user_id: str, content_type: str, content_id: str | None, text: str) -> int:
    if content_type == "message" and content_id:
        from apps.chat.services import moderate_message

        return moderate_message(content_id)
    flags = scan_text(text)
    if not flags:
        return 0
    ModerationFlagRecord.objects.create(
        subject_user_id=subject_user_id,
        content_type=content_type,
        content_id=content_id,
        content_digest=hashlib.sha256(text.encode()).hexdigest(),
        categories=[flag.category for flag in flags],
        layer=1,
        score=max(flag.score for flag in flags),
    )
    return len(flags)


@shared_task(queue="safety")
def dispatch_safety_delivery(delivery_id):
    from .delivery import process_delivery

    return process_delivery(delivery_id)


@shared_task(queue="safety")
def recover_safety_deliveries():
    from .delivery import dispatch_pending

    return dispatch_pending()


@shared_task(queue="safety")
def process_safety_checkins():
    from .scheduling import process_due_checkins

    return process_due_checkins()


@shared_task(queue="default")
def purge_safety_history():
    from .scheduling import purge_old_plans

    return purge_old_plans()


@shared_task(queue="safety")
def dispatch_panic_alert(alert_id):
    from .models import SafetyDelivery

    delivery = SafetyDelivery.objects.filter(alert_id=alert_id).first()
    return dispatch_safety_delivery(str(delivery.pk)) if delivery else "ignored"
