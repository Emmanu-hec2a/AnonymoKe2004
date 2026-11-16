from celery import shared_task

from .service import send_user_event


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def deliver_user_event(
    self,
    user_id: str,
    event_type: str,
    *,
    match_id: str | None = None,
    actor_alias: str | None = None,
):
    send_user_event(
        user_id=user_id,
        event_type=event_type,
        match_id=match_id,
        actor_alias=actor_alias,
    )
