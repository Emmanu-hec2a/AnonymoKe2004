from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import Purchase


@shared_task(queue="default")
def expire_stale_purchases() -> int:
    cutoff = timezone.now() - timedelta(minutes=30)
    return Purchase.objects.filter(
        status=Purchase.Status.PENDING, created_at__lt=cutoff
    ).update(status=Purchase.Status.EXPIRED, updated_at=timezone.now())
