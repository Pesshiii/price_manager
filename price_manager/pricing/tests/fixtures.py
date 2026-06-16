from supplier.models import Supplier
from product.models import Product, Category, Brand
from pricing.models import PriceType, PricingRule, ProductPrice, Stock


def make_price_type(name='закупочная', label='Закупочная'):
    return PriceType.objects.create(name=name, label=label)


def make_supplier(name='Test Supplier'):
    return Supplier.objects.create(name=name)


def make_product(sku='SKU-1', name='Test Product'):
    return Product.objects.create(sku=sku, name=name)


def make_feed(supplier, *, is_full_inventory=False):
    from dataframe.models import Dataframe
    from supplier_feed.models import FeedMapping, SupplierFeed

    df, _ = Dataframe.objects.get_or_create(
        name='Test Pipeline',
        defaults={'instructions': {'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []}},
    )
    mapping = FeedMapping.objects.create(
        supplier=supplier,
        name='Test Mapping',
        supplier_sku_column='article',
        dataframe=df,
        is_full_inventory=is_full_inventory,
    )
    feed = SupplierFeed.objects.create(supplier=supplier, feed_mapping=mapping, status='done')
    return feed, mapping


def price_column(mapping, col, price_type):
    from supplier_feed.models import FeedColumnMapping

    return FeedColumnMapping.objects.create(
        feed_mapping=mapping, column_name=col, role='price', price_type=price_type,
    )


def stock_column(mapping, col='qty'):
    from supplier_feed.models import FeedColumnMapping

    return FeedColumnMapping.objects.create(feed_mapping=mapping, column_name=col, role='stock')


def make_entry(feed, product, data):
    from supplier_feed.models import SupplierFeedEntry

    return SupplierFeedEntry.objects.create(
        feed=feed, product=product, supplier_sku=product.sku, data=data,
    )
