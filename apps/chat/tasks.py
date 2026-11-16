import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from .models import Message

logger = logging.getLogger("anonymoke.chat")


@shared_task(queue="moderation")
def retry_pending_moderation():
    from apps.safety.tasks import scan_content

    cutoff = timezone.now() - timedelta(minutes=5)
    messages = (
        Message.objects.filter(moderation_status="queued", deleted_at__isnull=True)
        .filter(Q(moderation_queued_at__isnull=True) | Q(moderation_queued_at__lt=cutoff))
        .select_related("sender")
        .order_by("created_at")[:100]
    )
    count = 0
    for message in messages:
        try:
            scan_content.delay(str(message.sender.user_id), "message", str(message.id), "")
        except Exception:  # noqa: BLE001 - retain pending messages for the next retry
            logger.warning("pending_moderation_queue_unavailable", exc_info=True)
            break
        Message.objects.filter(pk=message.pk).update(moderation_queued_at=timezone.now())
        count += 1
    return count
