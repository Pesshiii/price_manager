from django.db import migrations, models


def seed_products_from_main_product_pim_ids(apps, schema_editor):
    """Create a bare Product (pim_id only, number left null) for every
    distinct MainProduct.pim_id that doesn't already have one. These are
    placeholders - product/services/pim_sync.py::sync_product_from_pim
    is expected to fill in number/name/raw_data/categories later.

    Requires 0003 (number made nullable) to already be applied: number
    can't be left at its old implicit "" default here, since more than one
    row sharing "" would violate number's unique constraint.
    """
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    Product = apps.get_model('product', 'Product')
    Product.objects.all().delete()  # delete any existing products, since we don't know if they were created from pim_ids that have since been deleted
    pim_ids = (
        MainProduct.objects
        .exclude(pim_id__isnull=True)
        .exclude(pim_id='')
        .order_by()
        .values_list('pim_id', flat=True)
        .distinct()
    )
    existing = set(Product.objects.values_list('pim_id', flat=True))

    Product.objects.bulk_create(
        [Product(pim_id=pim_id, number=None) for pim_id in pim_ids if pim_id not in existing]
    )


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0004_alter_product_number'),
        ('main_product_manager', '0008_remove_mp_unique_supplier_article_name'),
    ]

    operations = [
        migrations.RunPython(seed_products_from_main_product_pim_ids, reverse_code=migrations.RunPython.noop),
    ]
