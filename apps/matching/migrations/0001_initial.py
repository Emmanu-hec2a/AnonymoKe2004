import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("profiles", "0003_mediaasset")]

    operations = [
        migrations.CreateModel(
            name="Swipe",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("like", "Like"), ("pass", "Pass")], max_length=8)),
                ("client_swipe_id", models.UUIDField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("from_profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="swipes_made", to="profiles.profile")),
                ("to_profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="swipes_received", to="profiles.profile")),
            ],
            options={
                "indexes": [models.Index(fields=["to_profile", "action", "created_at"], name="matching_sw_to_profi_65a9c2_idx"), models.Index(fields=["from_profile", "created_at"], name="matching_sw_from_pr_29954b_idx")],
                "constraints": [models.UniqueConstraint(fields=("from_profile", "to_profile"), name="unique_swipe_direction"), models.UniqueConstraint(fields=("from_profile", "client_swipe_id"), name="unique_client_swipe"), models.CheckConstraint(condition=models.Q(("from_profile", models.F("to_profile")), _negated=True), name="swipe_cannot_target_self")],
            },
        ),
        migrations.CreateModel(
            name="Match",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("state", models.CharField(choices=[("masked", "Masked"), ("unmasked", "Unmasked"), ("closed", "Closed")], default="masked", max_length=16)),
                ("a_unmask_consent_at", models.DateTimeField(blank=True, null=True)),
                ("b_unmask_consent_at", models.DateTimeField(blank=True, null=True)),
                ("a_unmask_declined_at", models.DateTimeField(blank=True, null=True)),
                ("b_unmask_declined_at", models.DateTimeField(blank=True, null=True)),
                ("unmasked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="matches_closed", to="profiles.profile")),
                ("profile_a", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="matches_as_a", to="profiles.profile")),
                ("profile_b", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="matches_as_b", to="profiles.profile")),
            ],
            options={
                "indexes": [models.Index(fields=["profile_a", "state"], name="matching_ma_profile_3b1bca_idx"), models.Index(fields=["profile_b", "state"], name="matching_ma_profile_9dfb6f_idx")],
                "constraints": [models.UniqueConstraint(fields=("profile_a", "profile_b"), name="unique_match_pair"), models.CheckConstraint(condition=models.Q(("profile_a", models.F("profile_b")), _negated=True), name="match_cannot_target_self")],
            },
        ),
    ]
