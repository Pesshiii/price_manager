from django.db import migrations, models


def copy_update_main_to_new_flags(apps, schema_editor):
    Setting = apps.get_model('supplier_product_manager', 'Setting')
    Setting.objects.update(
        update_main_content=models.F('update_main'),
        add_main_products=models.F('update_main'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_product_manager', '0003_alter_supplierproduct_main_product'),
    ]

    operations = [
        migrations.AddField(
            model_name='setting',
            name='update_main_content',
            field=models.BooleanField(default=True, verbose_name='Обновлять данные по товарам (контент) в ГП'),
        ),
        migrations.AddField(
            model_name='setting',
            name='add_main_products',
            field=models.BooleanField(default=True, verbose_name='Добавлять новые товары в ГП'),
        ),
        migrations.AlterField(
            model_name='setting',
            name='priced_only',
            field=models.BooleanField(default=True, verbose_name='Не добавлять товары без цены поставщика'),
        ),
        migrations.AlterField(
            model_name='setting',
            name='differ_by_name',
            field=models.BooleanField(default=True, verbose_name='Сопоставлять товары по названию и артикулу поставщика'),
        ),
        migrations.RunPython(copy_update_main_to_new_flags, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='setting',
            name='update_main',
        ),
    ]
