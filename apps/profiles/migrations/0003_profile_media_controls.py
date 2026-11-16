from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("profiles", "0003_mediaasset")]
    operations = [
        migrations.AddField(model_name="profile", name="audio_disguised", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="mediaasset", name="disguise_voice", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="mediaasset", name="processing_attempts", field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddField(model_name="mediaasset", name="processing_queued_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddIndex(model_name="mediaasset", index=models.Index(fields=["status", "processing_queued_at"], name="profile_media_pending")),
    ]
