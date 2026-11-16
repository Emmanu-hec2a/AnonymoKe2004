import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class VerificationAttempt(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        REVIEW = "review", "Review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_attempts"
    )
    provider = models.CharField(max_length=64)
    purpose = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    provider_reference_hash = models.CharField(max_length=64, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    launch_url_ciphertext = models.BinaryField(blank=True, default=bytes)
    expires_at = models.DateTimeField(null=True, blank=True)
    provider_job_id = models.CharField(max_length=64, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class VerificationResultCheck(models.Model):
    """Durable callback hints. Only a provider lookup can change verification."""

    attempt = models.ForeignKey(VerificationAttempt, on_delete=models.CASCADE)
    job_id = models.CharField(max_length=64)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["attempt", "job_id"], name="unique_verification_check")
        ]
