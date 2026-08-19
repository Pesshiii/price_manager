from django.db import migrations, models


def clear_link_values(apps, schema_editor):
    Link = apps.get_model('supplier_product_manager', 'Link')
    Link.objects.update(value=None)


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_product_manager', '0006_copysupplierproductstomainrun'),
    ]

    operations = [
        migrations.RunPython(clear_link_values, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='link',
            name='value',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
