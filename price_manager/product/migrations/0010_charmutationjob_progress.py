from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0009_importjob_progress'),
    ]

    operations = [
        migrations.AddField(
            model_name='characteristicmutationjob',
            name='rows_total',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='characteristicmutationjob',
            name='rows_done',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
