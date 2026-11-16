from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import MagicLinkToken, RefreshSession


@shared_task(queue="default")
def purge_expired_auth_records() -> dict[str, int]:
    """Remove expired one-time tokens and old refresh-session rows."""
    now = timezone.now()
    magic_deleted, _ = MagicLinkToken.objects.filter(
        expires_at__lt=now - timedelta(days=1)
    ).delete()
    refresh_deleted, _ = RefreshSession.objects.filter(
        expires_at__lt=now - timedelta(days=1)
    ).delete()
    return {"magic_link_tokens": magic_deleted, "refresh_sessions": refresh_deleted}
