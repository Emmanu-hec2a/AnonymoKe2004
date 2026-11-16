import uuid

from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="VerificationAttempt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(max_length=64)),
                ("purpose", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("passed", "Passed"), ("failed", "Failed"), ("review", "Review")], default="pending", max_length=16)),
                ("provider_reference_hash", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="verification_attempts", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
