import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("matching", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Message",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("body", models.TextField(max_length=2000)),
                ("moderation_status", models.CharField(choices=[("queued", "Queued"), ("clear", "Clear"), ("flagged", "Flagged"), ("blocked", "Blocked")], default="queued", max_length=16)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("match", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="matching.match")),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages_sent", to="profiles.profile")),
            ],
            options={
                "indexes": [models.Index(fields=["match", "created_at"], name="chat_messag_match_id_39e06e_idx"), models.Index(fields=["match", "read_at"], name="chat_messag_match_id_2f7dd4_idx")],
            },
        ),
    ]
