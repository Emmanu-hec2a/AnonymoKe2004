import uuid

from django.db import models

from apps.profiles.models import Profile


class Swipe(models.Model):
    class Action(models.TextChoices):
        LIKE = "like", "Like"
        PASS = "pass", "Pass"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    from_profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="swipes_made")
    to_profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="swipes_received"
    )
    action = models.CharField(max_length=8, choices=Action.choices)
    client_swipe_id = models.UUIDField()
    is_undone = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["from_profile", "to_profile"], name="unique_swipe_direction"
            ),
            models.UniqueConstraint(
                fields=["from_profile", "client_swipe_id"], name="unique_client_swipe"
            ),
            models.CheckConstraint(
                condition=~models.Q(from_profile=models.F("to_profile")),
                name="swipe_cannot_target_self",
            ),
        ]
        indexes = [
            models.Index(fields=["to_profile", "action", "created_at"]),
            models.Index(fields=["from_profile", "created_at"]),
        ]


class Match(models.Model):
    class State(models.TextChoices):
        MASKED = "masked", "Masked"
        UNMASKED = "unmasked", "Unmasked"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile_a = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="matches_as_a")
    profile_b = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="matches_as_b")
    state = models.CharField(max_length=16, choices=State.choices, default=State.MASKED)
    a_unmask_consent_at = models.DateTimeField(null=True, blank=True)
    b_unmask_consent_at = models.DateTimeField(null=True, blank=True)
    a_unmask_declined_at = models.DateTimeField(null=True, blank=True)
    b_unmask_declined_at = models.DateTimeField(null=True, blank=True)
    unmasked_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name="matches_closed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile_a", "profile_b"], name="unique_match_pair"),
            models.CheckConstraint(
                condition=~models.Q(profile_a=models.F("profile_b")),
                name="match_cannot_target_self",
            ),
        ]
        indexes = [
            models.Index(fields=["profile_a", "state"]),
            models.Index(fields=["profile_b", "state"]),
        ]
