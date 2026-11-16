from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("verification", "0002_verificationattempt_reason_code")]
    operations = [
        migrations.AddField(model_name="verificationattempt", name="launch_url_ciphertext", field=models.BinaryField(blank=True, default=bytes)),
        migrations.AddField(model_name="verificationattempt", name="expires_at", field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name="verificationattempt", name="provider_job_id", field=models.CharField(max_length=64, blank=True)),
        migrations.AddField(model_name="verificationattempt", name="last_synced_at", field=models.DateTimeField(null=True, blank=True)),
    ]
