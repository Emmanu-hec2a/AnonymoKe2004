import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ConsentRecord(models.Model):
    class ConsentType(models.TextChoices):
        TERMS = "terms", "Terms"
        PRIVACY = "privacy", "Privacy"
        LOCATION = "location", "Location processing"
        VOICE = "voice", "Voice processing"
        SENSITIVE_DATA = "sensitive_data", "Sensitive data"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consents"
    )
    consent_type = models.CharField(max_length=32, choices=ConsentType.choices)
    version = models.CharField(max_length=64)
    granted = models.BooleanField()
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "consent_type", "granted_at"])]


class DataSubjectRequest(models.Model):
    class Kind(models.TextChoices):
        EXPORT = "export", "Export"
        ERASURE = "erasure", "Erasure"

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_proof = models.JSONField(default=dict, blank=True)


class WebDeletionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for email delivery"
        SENT = "sent", "Waiting for confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Email delivery failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    subject_request = models.OneToOneField(
        DataSubjectRequest, on_delete=models.SET_NULL, null=True, blank=True
    )
    token_hash = models.CharField(max_length=64, unique=True)
    token_ciphertext = models.BinaryField(default=bytes)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="web_erasure_dispatch_idx"),
            models.Index(fields=["expires_at"], name="web_erasure_expiry_idx"),
        ]


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_user_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=128)
    object_type = models.CharField(max_length=128)
    object_id = models.UUIDField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
