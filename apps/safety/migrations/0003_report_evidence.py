from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("safety", "0002_block")]

    operations = [
        migrations.AddField(
            model_name="report",
            name="evidence_message_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name="report",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "Open"),
                    ("review", "Review"),
                    ("resolved", "Resolved"),
                    ("dismissed", "Dismissed"),
                ],
                default="open",
                max_length=16,
            ),
        ),
    ]
