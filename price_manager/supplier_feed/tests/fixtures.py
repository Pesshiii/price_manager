"""Shared test helpers for supplier_feed tests."""
from supplier.models import Supplier
from supplier_feed.models import FeedMapping


def make_supplier(name='Тест Поставщик'):
    return Supplier.objects.get_or_create(name=name)[0]


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
