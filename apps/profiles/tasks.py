from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import Profile


@shared_task(queue="default")
def purge_stale_locations() -> int:
    """Delete cells older than the 30-day location-retention limit."""
    cutoff = timezone.now() - timedelta(days=30)
    return Profile.objects.filter(cell_updated_at__lt=cutoff).update(
        cell=None,
        cell_updated_at=None,
    )


from .tasks_media import process_media_asset  # noqa: E402,F401
