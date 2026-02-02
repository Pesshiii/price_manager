from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='grouping_priority',
            field=models.PositiveIntegerField(default=0, verbose_name='Приоритет при группировке'),
        ),
    ]
