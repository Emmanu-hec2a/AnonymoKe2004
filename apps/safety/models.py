import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.profiles.models import Profile


class Report(models.Model):
    class Reason(models.TextChoices):
        SOLICITATION = "solicitation", "Solicitation"
        SCAM = "scam", "Scam"
        HARASSMENT = "harassment", "Harassment"
        FAKE = "fake", "Fake profile"
        UNDERAGE = "underage", "Underage"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEW = "review", "Review"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_made"
    )
    reported = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_received"
    )
    reason = models.CharField(max_length=32, choices=Reason.choices)
    note = models.TextField(max_length=1000, blank=True)
    evidence_message_ids = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "reported", "reason"], name="unique_reporter_reason_target"
            )
        ]
        indexes = [models.Index(fields=["reported", "reason", "status"])]


class ModerationFlagRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content_type = models.CharField(max_length=32)
    content_id = models.UUIDField(null=True, blank=True)
    content_digest = models.CharField(max_length=64)
    categories = models.JSONField(default=list)
    layer = models.PositiveSmallIntegerField()
    score = models.FloatField()
    status = models.CharField(max_length=16, default="queued")
    created_at = models.DateTimeField(auto_now_add=True)


class Block(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blocker = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="blocks_made")
    blocked = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="blocks_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="unique_profile_block"),
            models.CheckConstraint(
                condition=~Q(blocker=models.F("blocked")), name="block_cannot_target_self"
            ),
        ]
        indexes = [models.Index(fields=["blocked", "created_at"])]


class TrustedContact(models.Model):
    """Encrypted emergency contact used only for user-initiated safety alerts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trusted_contact"
    )
    contact_name = models.CharField(max_length=80)
    phone_hash = models.CharField(max_length=64)
    phone_ciphertext = models.BinaryField(blank=True, default=bytes)
    is_verified = models.BooleanField(default=False)
    linked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trusted_safety_relationships",
    )
    invite_code_hash = models.CharField(max_length=64, blank=True)
    invite_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user", "updated_at"])]


class DateSession(models.Model):
    """A user-controlled date safety session with an approximate venue label."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SAFE = "safe", "Safe"
        PANIC = "panic", "Panic alert sent"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="date_sessions"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    starts_at = models.DateTimeField()
    venue_label = models.CharField(max_length=120)
    check_in_due_at = models.DateTimeField()
    share_approximate_location = models.BooleanField(default=False)
    trusted_contact_name = models.CharField(max_length=80)
    trusted_contact_phone_ciphertext = models.BinaryField(blank=True, default=bytes)
    trusted_contact_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shared_date_plans",
    )
    approximate_area = models.JSONField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    overdue_at = models.DateTimeField(null=True, blank=True)
    safe_at = models.DateTimeField(null=True, blank=True)
    panic_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="active"),
                name="unique_active_date_session_per_user",
            )
        ]
        indexes = [models.Index(fields=["user", "status", "starts_at"])]


class PanicAlert(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        STORED = "stored", "Saved in app"
        PUSH_ACCEPTED = "push_accepted", "Push accepted"
        ACKNOWLEDGED = "acknowledged", "Contact acknowledged"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="panic_alerts"
    )
    date_session = models.ForeignKey(
        DateSession, on_delete=models.CASCADE, related_name="panic_alerts"
    )
    idempotency_key = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STORED)
    provider_reference = models.CharField(max_length=128, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    triggered_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"], name="unique_user_panic_idempotency"
            )
        ]
        indexes = [models.Index(fields=["user", "status", "triggered_at"])]


class SafetyAlertRecipient(models.Model):
    class Status(models.TextChoices):
        UNREAD = "unread", "Unread"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alert = models.ForeignKey(PanicAlert, on_delete=models.CASCADE, related_name="recipients")
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_safety_alerts",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNREAD)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["alert", "recipient_user"], name="unique_safety_alert_recipient"
            )
        ]
        indexes = [models.Index(fields=["recipient_user", "status", "created_at"])]


class SafetyDelivery(models.Model):
    """Durable notification outbox; in-app records do not depend on push delivery."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(DateSession, on_delete=models.CASCADE, related_name="deliveries")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    alert = models.OneToOneField(
        PanicAlert, on_delete=models.CASCADE, null=True, blank=True, related_name="push_delivery"
    )
    event_type = models.CharField(max_length=48)
    dedupe_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=24, default="queued")
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="safety_delivery_pending")
        ]
