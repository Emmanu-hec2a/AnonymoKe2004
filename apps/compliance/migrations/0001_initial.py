import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("actor_user_id", models.UUIDField(blank=True, null=True)),
                ("action", models.CharField(max_length=128)),
                ("object_type", models.CharField(max_length=128)),
                ("object_id", models.UUIDField(blank=True, null=True)),
                ("reason", models.CharField(blank=True, max_length=500)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="ConsentRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("consent_type", models.CharField(choices=[("terms", "Terms"), ("privacy", "Privacy"), ("location", "Location processing"), ("voice", "Voice processing"), ("sensitive_data", "Sensitive data")], max_length=32)),
                ("version", models.CharField(max_length=64)),
                ("granted", models.BooleanField()),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="consents", to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["user", "consent_type", "granted_at"], name="compliance_c_user_id_8b4cc5_idx")]},
        ),
        migrations.CreateModel(
            name="DataSubjectRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("export", "Export"), ("erasure", "Erasure")], max_length=16)),
                ("status", models.CharField(choices=[("requested", "Requested"), ("processing", "Processing"), ("completed", "Completed"), ("failed", "Failed")], default="requested", max_length=16)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("completion_proof", models.JSONField(blank=True, default=dict)),
                ("user", models.ForeignKey(null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
