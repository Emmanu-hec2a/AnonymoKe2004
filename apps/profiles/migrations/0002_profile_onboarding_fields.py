from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("profiles", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[("M", "Man"), ("W", "Woman"), ("NB", "Non-binary")],
                max_length=2,
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="height_cm",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="language",
            field=models.CharField(default="en", max_length=2),
        ),
        migrations.AddField(
            model_name="profile",
            name="max_distance_km",
            field=models.PositiveSmallIntegerField(default=15),
        ),
        migrations.AddField(
            model_name="profile",
            name="min_age_pref",
            field=models.PositiveSmallIntegerField(default=18),
        ),
        migrations.AddField(
            model_name="profile",
            name="max_age_pref",
            field=models.PositiveSmallIntegerField(default=35),
        ),
    ]

