import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("chat", "0003_align_model_state")]
    operations = [
        migrations.CreateModel(name="ChatAttachment", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("kind", models.CharField(max_length=8, choices=[("image", "Image"), ("audio", "Voice note")])),
            ("status", models.CharField(max_length=16, default="pending", choices=[("pending", "Pending"), ("processing", "Processing"), ("ready", "Ready"), ("rejected", "Rejected")])),
            ("content_type", models.CharField(max_length=64)), ("size_bytes", models.PositiveIntegerField()),
            ("incoming_key", models.CharField(max_length=255, unique=True)), ("object_key", models.CharField(max_length=255, blank=True)),
            ("width", models.PositiveIntegerField(default=0)), ("height", models.PositiveIntegerField(default=0)),
            ("duration_ms", models.PositiveIntegerField(default=0)), ("disguise_voice", models.BooleanField(default=True)),
            ("rejection_code", models.CharField(max_length=64, blank=True)), ("processing_started_at", models.DateTimeField(null=True, blank=True)),
            ("attempts", models.PositiveSmallIntegerField(default=0)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("match", models.ForeignKey("matching.match", on_delete=django.db.models.deletion.CASCADE, related_name="chat_attachments")),
            ("sender", models.ForeignKey("profiles.profile", on_delete=django.db.models.deletion.CASCADE, related_name="chat_attachments")),
        ], options={"indexes": [models.Index(fields=["status", "processing_started_at"], name="chat_attachment_pending")]}),
        migrations.AddField("message", "reply_to", models.ForeignKey("chat.message", on_delete=django.db.models.deletion.SET_NULL, null=True, blank=True, related_name="replies")),
        migrations.AddField("message", "attachment", models.OneToOneField("chat.chatattachment", on_delete=django.db.models.deletion.SET_NULL, null=True, blank=True, related_name="message")),
        migrations.AddField("message", "delivered_at", models.DateTimeField(null=True, blank=True)),
    ]
