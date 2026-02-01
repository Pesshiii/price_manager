from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_product_manager', '0005_setting_grouping_priority'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='setting',
            name='grouping_priority',
        ),
    ]
