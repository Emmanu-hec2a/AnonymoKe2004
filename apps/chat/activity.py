"""Short-lived activity scoped to a conversation, never global last-seen history."""

import logging
import threading
import time
from functools import lru_cache

import redis
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache

from apps.matching.services import participant_match

_lock = threading.Lock()


@lru_cache(maxsize=4)
def _redis(url):
    return redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)


def _keys(match, profile):
    return f"chat:presence:{match.pk}:{profile.pk}", f"chat:typing:{match.pk}:{profile.pk}"


def _state(match, profile, session=None, *, active=True, typing=False):
    now = time.time()
    keys = _keys(match, profile)
    try:
        if settings.CACHES["default"]["BACKEND"].endswith("LocMemCache"):
            with _lock:
                records = []
                for index, key in enumerate(keys):
                    values = {k: v for k, v in cache.get(key, {}).items() if v > now}
                    if session is not None:
                        values.pop(session, None)
                        if active and (index == 0 or typing):
                            values[session] = now + (45 if index == 0 else 6)
                        values = dict(sorted(values.items(), key=lambda item: item[1])[-8:])
                    cache.set(key, values, 50)
                    records.append(max(values.values(), default=0))
        else:
            client = _redis(settings.CACHES["default"]["LOCATION"])
            pipeline = client.pipeline(transaction=True)
            for index, key in enumerate(keys):
                pipeline.zremrangebyscore(key, "-inf", now)
                if session is not None:
                    pipeline.zrem(key, session)
                    if active and (index == 0 or typing):
                        pipeline.zadd(key, {session: now + (45 if index == 0 else 6)})
                    pipeline.zremrangebyrank(key, 0, -9)
                pipeline.expire(key, 50)
                pipeline.zrange(key, -1, -1, withscores=True)
            pipeline.execute()
            # Read separately: mutation command counts vary with typing state.
            records = [
                max((score for _, score in client.zrange(key, -1, -1, withscores=True)), default=0)
                for key in keys
            ]
        return {
            "active": records[0] > now,
            "typing": records[0] > now and records[1] > now,
            "active_ttl": max(0, int(records[0] - now)),
            "typing_ttl": max(0, int(records[1] - now)),
        }
    except (redis.RedisError, OSError):
        return {"active": None, "typing": False, "active_ttl": 0, "typing_ttl": 0}


def peer_activity(profile, match_id):
    match = participant_match(profile, match_id)
    other = match.profile_b if match.profile_a_id == profile.pk else match.profile_a
    return _state(match, other)


def update_activity(profile, match_id, session, *, active, typing):
    match = participant_match(profile, match_id)
    _state(match, profile, session, active=active, typing=typing)
    layer = get_channel_layer()
    if layer:
        try:
            async_to_sync(layer.group_send)(f"match-{match_id}", {"type": "chat.activity"})
        except Exception:  # noqa: BLE001 - activity never prevents messaging
            logging.getLogger("anonymoke.chat").debug("chat_activity_realtime_unavailable")
    return peer_activity(profile, match_id)
