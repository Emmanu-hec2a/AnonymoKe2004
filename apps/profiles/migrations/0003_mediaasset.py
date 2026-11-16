import uuid

from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0002_profile_onboarding_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="MediaAsset",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("avatar", "Avatar"), ("audio", "Audio capsule")], max_length=16)),
                ("status", models.CharField(choices=[("pending", "Pending upload"), ("processing", "Processing"), ("ready", "Ready"), ("rejected", "Rejected")], default="pending", max_length=16)),
                ("content_type", models.CharField(max_length=64)),
                ("incoming_key", models.CharField(max_length=255, unique=True)),
                ("original_key", models.CharField(blank=True, max_length=255)),
                ("derived_key", models.CharField(blank=True, max_length=255)),
                ("size_bytes", models.PositiveIntegerField(default=0)),
                ("duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("rejection_code", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="media_assets", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["user", "kind", "status"], name="profiles_me_user_id_6b6e1a_idx")],
            },
        ),
    ]
