import uuid

from django.core import signing
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def encode_cursor(timestamp, object_id, salt):
    return signing.dumps([timestamp.isoformat(), str(object_id)], salt=salt, compress=True)


def decode_cursor(raw, salt):
    try:
        value = signing.loads(raw, salt=salt, max_age=86400)
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        timestamp = parse_datetime(value[0])
        if timestamp is None or timezone.is_naive(timestamp):
            raise ValueError
        return timestamp, uuid.UUID(value[1])
    except (signing.BadSignature, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("cursor_invalid") from exc
