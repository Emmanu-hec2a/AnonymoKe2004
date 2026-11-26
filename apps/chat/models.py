import uuid

from django.db import models

from apps.matching.models import Match
from apps.profiles.models import Profile


class Message(models.Model):
    class ModerationStatus(models.TextChoices):
        QUEUED = "queued", "Queued"
        CLEAR = "clear", "Clear"
        FLAGGED = "flagged", "Flagged"
        BLOCKED = "blocked", "Blocked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="messages_sent")
    body = models.TextField(max_length=2000)
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies"
    )
    attachment = models.OneToOneField(
        "ChatAttachment", on_delete=models.SET_NULL, null=True, blank=True, related_name="message"
    )
    client_message_id = models.UUIDField(null=True, blank=True)
    moderation_queued_at = models.DateTimeField(null=True, blank=True)
    moderation_status = models.CharField(
        max_length=16, choices=ModerationStatus.choices, default=ModerationStatus.QUEUED
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["match", "sender", "client_message_id"],
                name="unique_client_chat_message",
            )
        ]
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=models.Q(moderation_status="queued", deleted_at__isnull=True),
                name="chat_queued_moderation",
            ),
            models.Index(fields=["match", "created_at"]),
            models.Index(fields=["match", "read_at"]),
        ]


class ChatAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="chat_attachments")
    sender = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="chat_attachments")
    kind = models.CharField(max_length=8, choices=[("image", "Image"), ("audio", "Voice note")])
    status = models.CharField(
        max_length=16,
        default="pending",
        choices=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("ready", "Ready"),
            ("rejected", "Rejected"),
        ],
    )
    content_type = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    incoming_key = models.CharField(max_length=255, unique=True)
    object_key = models.CharField(max_length=255, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    disguise_voice = models.BooleanField(default=True)
    rejection_code = models.CharField(max_length=64, blank=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "processing_started_at"], name="chat_attachment_pending")
        ]
