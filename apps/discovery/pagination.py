"""Private keyset cursors: browsing never records a swipe or exposes exact distance."""

import hashlib
import json
import math
import uuid

from django.contrib.gis.measure import D
from django.core import signing
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.crypto import decrypt_text, encrypt_text

from .services import candidate_queryset

ORDER = (
    ("liked_me", True),
    ("boost_active", True),
    ("distance_m", False),
    ("verification_level", True),
    ("updated_at", True),
    ("id", False),
)
SALT = "anonymoke.discovery.v1"


def _scope(me, filters):
    value = {
        "owner": str(me.pk),
        "cell": me.cell.wkt if me.cell else None,
        "gender": me.gender,
        "age": me.age_years,
        "targets": sorted(me.matching_preference.target_genders),
        "ages": [me.min_age_pref, me.max_age_pref],
        "radius": me.max_distance_km,
        "filters": filters,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def candidate_page(me, *, cursor=None, limit=20, **filters):
    # Access/consent checks apply even to a valid cursor from an earlier request.
    queryset = candidate_queryset(me, **filters)
    scope = _scope(me, filters)
    at = timezone.now()
    position = None
    if cursor:
        try:
            if len(cursor) > 4096:
                raise ValueError
            encrypted = signing.loads(cursor, salt=SALT, max_age=1800)
            data = json.loads(decrypt_text(encrypted.encode()))
            if data["scope"] != scope or len(data["position"]) != len(ORDER):
                raise ValueError
            at = parse_datetime(data["at"])
            position = data["position"]
            if at is None or timezone.is_naive(at):
                raise ValueError
            if any(type(position[i]) is not bool for i in (0, 1)):
                raise ValueError
            distance = float(position[2])
            if not math.isfinite(distance) or distance < 0:
                raise ValueError
            modified = parse_datetime(position[4])
            if modified is None or timezone.is_naive(modified):
                raise ValueError
            position = [
                position[0],
                position[1],
                D(m=distance),
                position[3],
                modified,
                uuid.UUID(position[5]),
            ]
        except (signing.BadSignature, ValueError, TypeError, KeyError, AttributeError) as error:
            raise ValueError("cursor_invalid") from error
    queryset = candidate_queryset(me, ranking_at=at, **filters).filter(created_at__lte=at)
    if position is not None:
        after = Q(pk__in=[])
        prefix = {}
        for (field, descending), value in zip(ORDER, position, strict=True):
            after |= Q(**prefix, **{f"{field}__{'lt' if descending else 'gt'}": value})
            prefix[field] = value
        queryset = queryset.filter(after)
    rows = list(queryset[: limit + 1])
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        data = {
            "scope": scope,
            "at": at.isoformat(),
            "position": [
                bool(last.liked_me),
                bool(last.boost_active),
                last.distance_m.m,
                last.verification_level,
                last.updated_at.isoformat(),
                str(last.pk),
            ],
        }
        next_cursor = signing.dumps(encrypt_text(json.dumps(data)).decode(), salt=SALT)
    return items, next_cursor
