from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0008_product_embedding'),
    ]

    operations = [
        migrations.AddField(
            model_name='importjob',
            name='rows_total',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='importjob',
            name='rows_done',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
