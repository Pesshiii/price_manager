from django.db import migrations, models


def copy_delivery_days_to_split_fields(apps, schema_editor):
    Supplier = apps.get_model('supplier_manager', 'Supplier')
    for supplier in Supplier.objects.all().only('id', 'delivery_days'):
        Supplier.objects.filter(pk=supplier.pk).update(
            delivery_days_available=supplier.delivery_days,
            delivery_days_navailable=supplier.delivery_days,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0006_remove_supplier_grouping_priority'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='delivery_days_available',
            field=models.PositiveIntegerField(default=0, verbose_name='Срок поставки (Рабочие дни) при наличии'),
        ),
        migrations.AddField(
            model_name='supplier',
            name='delivery_days_navailable',
            field=models.PositiveIntegerField(default=0, verbose_name='Срок поставки (Рабочие дни) при отсутствии'),
        ),
        migrations.RunPython(copy_delivery_days_to_split_fields, migrations.RunPython.noop),
    ]
