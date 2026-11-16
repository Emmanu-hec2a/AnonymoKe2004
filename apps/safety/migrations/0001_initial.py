import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ModerationFlagRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("content_type", models.CharField(max_length=32)),
                ("content_id", models.UUIDField(blank=True, null=True)),
                ("content_digest", models.CharField(max_length=64)),
                ("categories", models.JSONField(default=list)),
                ("layer", models.PositiveSmallIntegerField()),
                ("score", models.FloatField()),
                ("status", models.CharField(default="queued", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("subject_user", models.ForeignKey(on_delete=models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Report",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reason", models.CharField(choices=[("solicitation", "Solicitation"), ("scam", "Scam"), ("harassment", "Harassment"), ("fake", "Fake profile"), ("underage", "Underage"), ("other", "Other")], max_length=32)),
                ("note", models.TextField(blank=True, max_length=1000)),
                ("status", models.CharField(choices=[("open", "Open"), ("review", "Review"), ("resolved", "Resolved")], default="open", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reported", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="reports_received", to=settings.AUTH_USER_MODEL)),
                ("reporter", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="reports_made", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["reported", "reason", "status"], name="safety_rep_reported_eea4c6_idx")],
                "constraints": [models.UniqueConstraint(fields=("reporter", "reported", "reason"), name="unique_reporter_reason_target")],
            },
        ),
    ]
