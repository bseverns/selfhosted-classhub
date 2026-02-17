# Generated manually to align StudentEvent index names with Django's 30-char limit.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0007_studentevent"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="studentevent",
            old_name="hub_studente_event_t_e17920_idx",
            new_name="hub_student_event_t_387746_idx",
        ),
        migrations.RenameIndex(
            model_name="studentevent",
            old_name="hub_studente_classro_d3d6f9_idx",
            new_name="hub_student_classro_a0c234_idx",
        ),
        migrations.RenameIndex(
            model_name="studentevent",
            old_name="hub_studente_student_43a607_idx",
            new_name="hub_student_student_01e0d2_idx",
        ),
    ]
