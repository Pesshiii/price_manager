from django.db import migrations
from django.db.models import Count


def decouple_shared_main_products(apps, schema_editor):
    """One MainProduct can currently be linked from several SupplierProducts
    (produced by the now-retired "merge duplicate MainProducts" feature,
    which re-pointed every SupplierProduct from the losing MainProducts onto
    one survivor). Before main_product can become unique (migration 0009),
    every MainProduct must be split back down to at most one link: keep the
    SupplierProduct whose own (supplier, article, name) matches the
    MainProduct's own fields (the one that originally created/matched it via
    the normal copy pipeline), and give every other linked SupplierProduct
    its own new MainProduct, cloned the same way
    copy_supplier_products_to_main_task creates one for an unlinked
    SupplierProduct.

    Kept in its own migration, separate from the AlterField that adds the
    unique constraint: inserting rows here and then altering a FK pointing
    at the same table in one atomic migration makes Postgres refuse the
    ALTER TABLE with "cannot ALTER TABLE ... because it has pending trigger
    events" - splitting lets this data migration's changes commit first.
    """
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    SupplierProduct = apps.get_model('supplier_product_manager', 'SupplierProduct')
    CategoryThrough = MainProduct.categories.through
    PriceTag = apps.get_model('product_price_manager', 'PriceTag')
    PriceTag.objects.all().delete()
    MainProduct.objects.all().update(
        stock=0,
        prime_cost=0, 
        wholesale_price=0, 
        basic_price=0, 
        m_price=0, 
        wholesale_price_extra=0, 
        discount_price=0
        )
    shared_mp_ids = (
        SupplierProduct.objects.filter(main_product__isnull=False)
        .values('main_product')
        .annotate(c=Count('id'))
        .filter(c__gt=1)
        .values_list('main_product', flat=True)
    )

    for mp in MainProduct.objects.filter(id__in=list(shared_mp_ids)):
        sps = list(mp.supplierproducts.select_related('supplier').order_by('id'))
        keeper = next(
            (sp for sp in sps
             if sp.supplier_id == mp.supplier_id and sp.article == mp.article and sp.name == mp.name),
            sps[0],
        )
        for sp in sps:
            if sp.id == keeper.id:
                continue

            prefix = (sp.supplier.sku_value or '') if sp.supplier.sku_type == 'prefix' else ''
            suffix = (sp.supplier.sku_value or '') if sp.supplier.sku_type == 'suffix' else ''
            new_mp = MainProduct.objects.create(
                supplier_id=sp.supplier_id,
                article=sp.article,
                name=sp.name,
                sku=f'{prefix}{sp.article}{suffix}',
                description=sp.description,
                manufacturer_id=sp.manufacturer_id,
            )
            if sp.category_id:
                CategoryThrough.objects.create(mainproduct_id=new_mp.id, category_id=sp.category_id)

            sp.main_product_id = new_mp.id
            sp.save(update_fields=['main_product'])


class Migration(migrations.Migration):

    dependencies = [
        ('main_product_manager', '0008_remove_mp_unique_supplier_article_name'),
        ('supplier_product_manager', '0007_supplierproduct_pim_id'),
    ]

    operations = [
        migrations.RunPython(decouple_shared_main_products, reverse_code=migrations.RunPython.noop),
    ]
