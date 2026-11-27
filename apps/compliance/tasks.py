from celery import shared_task

from .web_erasure import process, recover


@shared_task(queue="default")
def process_web_deletion(request_id):
    process(request_id)


@shared_task(queue="default")
def recover_web_deletions():
    recover()
