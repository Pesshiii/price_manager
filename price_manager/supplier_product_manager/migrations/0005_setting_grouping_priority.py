from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_product_manager', '0004_setting_main_product_flags'),
    ]

    operations = [
        migrations.AddField(
            model_name='setting',
            name='grouping_priority',
            field=models.PositiveIntegerField(default=0, verbose_name='Приоритет при группировке'),
        ),
    ]
