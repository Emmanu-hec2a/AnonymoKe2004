from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("verification", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="verificationattempt",
            name="reason_code",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
