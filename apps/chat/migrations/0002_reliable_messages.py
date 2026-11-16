from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("chat", "0001_initial")]
    operations = [
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["created_at"],
                condition=models.Q(moderation_status="queued", deleted_at__isnull=True),
                name="chat_queued_moderation",
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="client_message_id",
            field=models.UUIDField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="message",
            name="moderation_queued_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddConstraint(
            model_name="message",
            constraint=models.UniqueConstraint(
                fields=["match", "sender", "client_message_id"],
                name="unique_client_chat_message",
            ),
        ),
    ]
