from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("matching", "0001_initial")]
    operations = [migrations.AddField(
        model_name="swipe", name="is_undone", field=models.BooleanField(default=False),
    )]
