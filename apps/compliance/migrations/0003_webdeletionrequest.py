import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("compliance", "0002_align_model_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="WebDeletionRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("token_ciphertext", models.BinaryField(default=bytes)),
                ("status", models.CharField(choices=[("pending", "Waiting for email delivery"), ("sent", "Waiting for confirmation"), ("confirmed", "Confirmed"), ("processing", "Processing"), ("completed", "Completed"), ("failed", "Email delivery failed")], default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("next_attempt_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("lease_until", models.DateTimeField(blank=True, null=True)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("subject_request", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="compliance.datasubjectrequest")),
                ("user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [
                models.Index(fields=["status", "next_attempt_at"], name="web_erasure_dispatch_idx"),
                models.Index(fields=["expires_at"], name="web_erasure_expiry_idx"),
            ]},
        ),
    ]
