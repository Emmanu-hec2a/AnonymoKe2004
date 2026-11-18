from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("profiles", "0004_align_model_state")]

    operations = [
        migrations.AddField(
            model_name="mediaasset",
            name="thumbnail_key",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
