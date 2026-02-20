from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0009_class_session_epoch"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonrelease",
            name="helper_allowed_topics_override",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="lessonrelease",
            name="helper_context_override",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="lessonrelease",
            name="helper_reference_override",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="lessonrelease",
            name="helper_topics_override",
            field=models.TextField(blank=True, default=""),
        ),
    ]
