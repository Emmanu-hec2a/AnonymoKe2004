from celery import shared_task

from .services import expire_unanswered_likes


@shared_task(queue="default")
def expire_likes() -> int:
    return expire_unanswered_likes()
