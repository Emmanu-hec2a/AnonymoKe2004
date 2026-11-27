from celery import shared_task

from .service import PushDeliveryRetry, send_user_event


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    queue="default",
)
def deliver_user_event(
    self,
    user_id: str,
    event_type: str,
    *,
    match_id: str | None = None,
    actor_alias: str | None = None,
    device_ids: list[int] | None = None,
):
    try:
        result = send_user_event(
            user_id=user_id, event_type=event_type, match_id=match_id,
            actor_alias=actor_alias, device_ids=device_ids,
        )
        retry_ids = result.retry_device_ids
    except PushDeliveryRetry as error:
        retry_ids = error.device_ids
    if retry_ids:
        # Retry only failed devices. Already accepted devices must not receive
        # another notification because a different phone was temporarily offline.
        raise self.retry(
            args=(),
            kwargs={"user_id": user_id, "event_type": event_type,
                    "match_id": match_id, "actor_alias": actor_alias,
                    "device_ids": list(retry_ids)},
            exc=RuntimeError("push_temporarily_unavailable"),
            countdown=min(10 * 2**self.request.retries, 300),
        )
