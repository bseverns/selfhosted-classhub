from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0008_rename_studentevent_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="class",
            name="session_epoch",
            field=models.PositiveIntegerField(default=1),
        ),
    ]
