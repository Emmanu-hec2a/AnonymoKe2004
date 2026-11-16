import uuid

from django.db import models


class ProfileBoost(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey("profiles.Profile", on_delete=models.CASCADE, related_name="boosts")
    source_entitlement = models.ForeignKey(
        "store.Entitlement",
        on_delete=models.SET_NULL,
        null=True,
    )
    client_activation_id = models.UUIDField()
    activated_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "client_activation_id"],
                name="unique_boost_activation",
            )
        ]
        indexes = [models.Index(fields=["profile", "expires_at"], name="boost_profile_expiry_idx")]
