"""Shared test helpers for supplier_feed tests."""
from supplier_manager.models import Currency, Supplier
from supplier_feed.models import FeedMapping


def make_currency(name='KZT', value='1.00'):
    return Currency.objects.get_or_create(name=name, defaults={'value': value})[0]


def make_supplier(name='Тест Поставщик', currency=None):
    if currency is None:
        currency = make_currency()
    return Supplier.objects.get_or_create(
        name=name,
        defaults={
            'currency': currency,
            'price_update_rate': '',
            'stock_update_rate': '',
        },
    )[0]


def make_feed_mapping(supplier=None, name='Прайс', supplier_sku_column='article', **kwargs):
    if supplier is None:
        supplier = make_supplier()
    return FeedMapping.objects.create(
        supplier=supplier,
        name=name,
        supplier_sku_column=supplier_sku_column,
        **kwargs,
    )


def make_product(sku='PROD-001', name='Тест Товар', brand_name='Бренд', category_name='Категория'):
    """Create a minimal Product for use in supplier_feed tests."""
    from product.models import Brand, Category, Product
    brand, _ = Brand.objects.get_or_create(name=brand_name)
    category, _ = Category.objects.get_or_create(
        name=category_name,
        defaults={'slug': category_name.lower().replace(' ', '-')},
    )
    product, _ = Product.objects.get_or_create(
        sku=sku,
        defaults={'name': name, 'brand': brand, 'category': category},
    )
    return product
