"""MainProduct becomes a stock + price row: catalog fields dropped (Phase 2b, D12/D13).

search, name, brand and categories live on product.Product. No data migration
for description (D13): MainProduct.description was copied from the supplier
row by copy-to-main, and SupplierProduct.description stays. The step below
only counts the descriptions that exist nowhere else (F4) so the loss is on
record rather than silent.
"""

from django.db import migrations


def report_descriptions_without_a_source(apps, schema_editor):
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    orphaned = (
        MainProduct.objects.exclude(description__isnull=True).exclude(description='')
        .exclude(supplierproducts__description__gt='')
        .count()
    )
    print()
    print(f'  0012: описаний MainProduct без описания в строке прайса: {orphaned} — удаляются')


class Migration(migrations.Migration):

    dependencies = [
        ('main_product_manager', '0011_mainproduct_product_fk'),
        # The report reads SupplierProduct.description through the reverse relation.
        ('supplier_product_manager', '0009_alter_supplierproduct_main_product_unique'),
    ]

    operations = [
        migrations.RunPython(report_descriptions_without_a_source, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name='mainproduct',
            name='main_produc_search__b370a9_gin',
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='categories',
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='depth',
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='description',
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='length',
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='manufacturer',
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='search_vector',
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='weight',
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='width',
        ),
    ]
