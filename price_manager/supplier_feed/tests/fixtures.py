"""Shared test helpers for supplier_feed tests."""
from supplier.models import Supplier
from supplier_feed.models import FeedMapping


def make_supplier(name='Тест Поставщик'):
    return Supplier.objects.get_or_create(name=name)[0]


def make_dataframe(name='Test Pipeline'):
    from dataframe.models import Dataframe
    df, _ = Dataframe.objects.get_or_create(
        name=name,
        defaults={
            'instructions': {
                'reader': {'func': 'read_csv', 'args': {}},
                'transforms': [],
            }
        },
    )
    return df


def make_feed_mapping(supplier=None, name='Прайс', supplier_sku_column='article', **kwargs):
    if supplier is None:
        supplier = make_supplier()
    if 'dataframe' not in kwargs:
        kwargs['dataframe'] = make_dataframe()
    return FeedMapping.objects.create(
        supplier=supplier,
        name=name,
        supplier_sku_column=supplier_sku_column,
        **kwargs,
    )


def make_product(pim_id='PIM-001', number='PROD-001', name='Тест Товар'):
    """Create a minimal Product for use in supplier_feed tests (no live PIM call)."""
    from product.models import Product
    product, _ = Product.objects.get_or_create(
        pim_id=pim_id, defaults={'number': number, 'name': name},
    )
    return product
