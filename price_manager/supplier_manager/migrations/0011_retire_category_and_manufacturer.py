"""Retire supplier_manager.Category, Manufacturer and ManufacturerDict (Phase 2b-3).

Category is replaced by product.Category (D2), Manufacturer by product.Brand from
PIM (D1, D3). Every FK and M2M into these models was removed or repointed in
Phase 2b-2; those migrations are declared as dependencies below on purpose. The
autodetector cannot see that link — nothing in today's model state says those
fields ever pointed here — and a fresh-database migrate would pass in any order.
Only a populated database, where the old constraints still exist until those
migrations run, would fail. So the order is written down, not left to luck.

Before the tables go, ManufacturerDict — the supplier-spelling -> manufacturer
alias table — is written to media/exports/ as CSV. The user chose to keep that
knowledge for the PIM team, who are merging duplicate brand spellings in PIM
(R5: 14 case-only duplicate groups found, 2026-09-21). If the file cannot be
written, the migration fails before anything is dropped.
"""

import csv
import io

from django.db import migrations


def export_manufacturer_aliases(apps, schema_editor):
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    ManufacturerDict = apps.get_model('supplier_manager', 'ManufacturerDict')
    rows = list(
        ManufacturerDict.objects.order_by('manufacturer__name', 'name')
        .values_list('name', 'manufacturer__name')
    )
    print()
    if not rows:
        print('  0011: словарь написаний производителей пуст — выгружать нечего')
        return
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['Написание у поставщика', 'Производитель'])
    writer.writerows(rows)
    # BOM — чтобы Excel прочитал кириллицу.
    path = default_storage.save(
        'exports/manufacturer_aliases.csv',
        ContentFile(('﻿' + buffer.getvalue()).encode('utf-8')),
    )
    print(f'  0011: словарь написаний производителей ({len(rows)} строк) выгружен в media/{path}')


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0010_supplier_price_priority_supplier_stock_priority'),
        # Every reference into the three models is gone only after these run.
        ('main_product_manager', '0012_drop_catalog_fields'),
        ('supplier_product_manager', '0010_drop_category_and_manufacturer'),
        ('product_price_manager', '0004_categories_to_product_category'),
        # product.0002 заводил product.brand -> Manufacturer, product.0003 его
        # убрал; удалять Manufacturer можно только после этого.
        ('product', '0003_alter_product_number_alter_product_pim_id'),
    ]

    operations = [
        migrations.RunPython(export_manufacturer_aliases, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='manufacturerdict',
            name='manufacturer',
        ),
        migrations.DeleteModel(
            name='Category',
        ),
        migrations.DeleteModel(
            name='Manufacturer',
        ),
        migrations.DeleteModel(
            name='ManufacturerDict',
        ),
    ]
