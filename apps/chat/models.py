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
    client_message_id = models.UUIDField(null=True, blank=True)
    moderation_queued_at = models.DateTimeField(null=True, blank=True)
    moderation_status = models.CharField(
        max_length=16, choices=ModerationStatus.choices, default=ModerationStatus.QUEUED
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
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
