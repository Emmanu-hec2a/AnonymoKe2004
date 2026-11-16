import uuid

from django.conf import settings
from django.contrib.gis.db import models


class Profile(models.Model):
    class Gender(models.TextChoices):
        M = "M", "Man"
        W = "W", "Woman"
        NB = "NB", "Non-binary"

    class VerificationLevel(models.TextChoices):
        NONE = "none", "None"
        AGE_VERIFIED = "age_verified", "Age verified"
        VERIFIED = "verified", "Verified"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    alias = models.CharField(max_length=40, blank=True)
    gender = models.CharField(max_length=2, choices=Gender.choices, blank=True)
    age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_date_ciphertext = models.BinaryField(blank=True, default=bytes)
    height_cm = models.PositiveSmallIntegerField(null=True, blank=True)
    bio = models.TextField(max_length=300, blank=True)
    interests = models.JSONField(default=list, blank=True)
    language = models.CharField(max_length=2, default="en")
    blurred_avatar_key = models.CharField(max_length=255, blank=True)
    audio_key = models.CharField(max_length=255, blank=True)
    audio_duration_ms = models.PositiveIntegerField(default=0)
    audio_disguised = models.BooleanField(default=False)
    cell = models.PointField(geography=True, srid=4326, null=True, blank=True)
    cell_updated_at = models.DateTimeField(null=True, blank=True)
    location_flagged = models.BooleanField(default=False)
    verification_level = models.CharField(
        max_length=20, choices=VerificationLevel.choices, default=VerificationLevel.NONE
    )
    is_discoverable = models.BooleanField(default=True)
    max_distance_km = models.PositiveSmallIntegerField(default=15)
    min_age_pref = models.PositiveSmallIntegerField(default=18)
    max_age_pref = models.PositiveSmallIntegerField(default=35)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PrivateIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="private_identity"
    )
    username = models.CharField(max_length=20, unique=True, null=True, blank=True)
    real_first_name_ciphertext = models.BinaryField(blank=True, default=bytes)
    real_avatar_key = models.CharField(max_length=255, blank=True)
    social_handles_ciphertext = models.BinaryField(blank=True, default=bytes)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class MatchingPreference(models.Model):
    """Sensitive preference data; never serialize, export, or expose to admin views."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.OneToOneField(
        Profile, on_delete=models.CASCADE, related_name="matching_preference"
    )
    target_genders = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)


class MediaAsset(models.Model):
    class Kind(models.TextChoices):
        AVATAR = "avatar", "Avatar"
        AUDIO = "audio", "Audio capsule"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending upload"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="media_assets"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    content_type = models.CharField(max_length=64)
    incoming_key = models.CharField(max_length=255, unique=True)
    original_key = models.CharField(max_length=255, blank=True)
    derived_key = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    rejection_code = models.CharField(max_length=64, blank=True)
    disguise_voice = models.BooleanField(default=True)
    processing_attempts = models.PositiveSmallIntegerField(default=0)
    processing_queued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "kind", "status"]),
            models.Index(fields=["status", "processing_queued_at"], name="profile_media_pending"),
        ]
