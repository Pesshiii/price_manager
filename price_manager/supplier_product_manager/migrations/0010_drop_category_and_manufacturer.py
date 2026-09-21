"""SupplierProduct.category / .manufacturer dropped (Phase 2b, D1/D11).

Run only after P2-G4's manufacturer export was taken in production and handed
over — this deletes the only copy of that data.

The Link rows that mapped a supplier-file column onto either field are deleted
first and counted, not silently: after the drop they would name a field that
no longer exists. load_setting() now ignores keys outside LINKS anyway, but a
leftover row would still show up on the mapping screen.
"""

from django.db import migrations, models


DROPPED_KEYS = ('category', 'manufacturer')


def delete_links_to_dropped_columns(apps, schema_editor):
    Link = apps.get_model('supplier_product_manager', 'Link')
    DictItem = apps.get_model('supplier_product_manager', 'DictItem')
    links = Link.objects.filter(key__in=DROPPED_KEYS)
    per_key = {key: links.filter(key=key).count() for key in DROPPED_KEYS}
    dict_items = DictItem.objects.filter(link__in=links).count()
    links.delete()
    print()
    print(f'  0010: удалено сопоставлений столбцов: {per_key} '
          f'(с их словарными заменами: {dict_items})')


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_product_manager', '0009_alter_supplierproduct_main_product_unique'),
    ]

    operations = [
        migrations.RunPython(delete_links_to_dropped_columns, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='supplierproduct',
            name='category',
        ),
        migrations.RemoveField(
            model_name='supplierproduct',
            name='manufacturer',
        ),
        migrations.AlterField(
            model_name='link',
            name='key',
            field=models.CharField(choices=[('', 'Не включать'), ('article', 'Артикул поставщика'), ('name', 'Название'), ('description', 'Описание'), ('discount', 'Группа скидок'), ('stock', 'Остаток'), ('supplier_price', 'Цена поставщика в валюте поставщика'), ('rrp', 'РРЦ в валюте поставщика'), ('discount_price', 'Цена со скидкой в валюте поставщика')]),
        ),
    ]
