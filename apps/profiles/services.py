import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.contrib.gis.geos import Point
from django.utils import timezone

from .models import Profile

DISTANCE_BUCKETS = ("<1 km", "1-2 km", "2-5 km", "5-10 km", "10-25 km", "25+ km")


@dataclass(frozen=True)
class LocationUpdateResult:
    flagged: bool
    cell_updated_at: datetime


def _offset_for_user(user_id: str) -> tuple[float, float]:
    digest = hmac.new(
        settings.LOCATION_HMAC_SECRET.encode(), user_id.encode(), hashlib.sha256
    ).digest()
    lat_fraction = int.from_bytes(digest[:4], "big") / 2**32
    lon_fraction = int.from_bytes(digest[4:8], "big") / 2**32
    return ((lat_fraction * 2 - 1) * 0.0025, (lon_fraction * 2 - 1) * 0.0025)


def update_snapped_location(
    profile: Profile,
    *,
    latitude: float,
    longitude: float,
    accuracy_m: float,
    is_mock: bool,
    captured_at: datetime,
) -> LocationUpdateResult:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("invalid_coordinates")
    if accuracy_m > 2000:
        raise ValueError("location_accuracy_too_low")
    now = timezone.now()
    if captured_at > now + timedelta(minutes=5):
        raise ValueError("captured_at_in_future")
    if profile.cell_updated_at:
        if captured_at <= profile.cell_updated_at:
            raise ValueError("location_timestamp_older_than_last")
        if (captured_at - profile.cell_updated_at).total_seconds() < 60:
            raise ValueError("location_rate_limited")
    if is_mock:
        profile.location_flagged = True
        profile.save(update_fields=["location_flagged", "updated_at"])
        return LocationUpdateResult(
            flagged=True,
            cell_updated_at=profile.cell_updated_at or captured_at,
        )
    offset_lat, offset_lon = _offset_for_user(str(profile.user_id))
    snapped_lat = round((latitude + offset_lat) / 0.005) * 0.005
    snapped_lon = round((longitude + offset_lon) / 0.005) * 0.005
    if profile.cell and profile.cell_updated_at:
        distance = _haversine_km(profile.cell.y, profile.cell.x, snapped_lat, snapped_lon)
        elapsed_hours = (captured_at - profile.cell_updated_at).total_seconds() / 3600
        if elapsed_hours > 0 and distance / elapsed_hours > 150:
            profile.location_flagged = True
            profile.save(update_fields=["location_flagged", "updated_at"])
            raise ValueError("location_teleport_detected")
    profile.cell = Point(snapped_lon, snapped_lat, srid=4326)
    profile.cell_updated_at = captured_at.astimezone(UTC)
    profile.location_flagged = False
    profile.save(update_fields=["cell", "cell_updated_at", "location_flagged", "updated_at"])
    return LocationUpdateResult(flagged=bool(is_mock), cell_updated_at=profile.cell_updated_at)


def _haversine_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius_km = 6371.0088
    lat_delta = math.radians(lat_b - lat_a)
    lon_delta = math.radians(lon_b - lon_a)
    a = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(math.radians(lat_a))
        * math.cos(math.radians(lat_b))
        * math.sin(lon_delta / 2) ** 2
    )
    return radius_km * 2 * math.asin(math.sqrt(a))


def distance_bucket(distance_km: float) -> str:
    if distance_km < 1:
        return DISTANCE_BUCKETS[0]
    if distance_km < 2:
        return DISTANCE_BUCKETS[1]
    if distance_km < 5:
        return DISTANCE_BUCKETS[2]
    if distance_km < 10:
        return DISTANCE_BUCKETS[3]
    if distance_km < 25:
        return DISTANCE_BUCKETS[4]
    return DISTANCE_BUCKETS[5]
