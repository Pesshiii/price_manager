from supplier.models import Supplier
from product.models import Product, Category, Brand
from pricing.models import PriceType, PricingRule, ProductPrice, Stock


def make_price_type(name='закупочная', label='Закупочная'):
    return PriceType.objects.create(name=name, label=label)


def make_supplier(name='Test Supplier'):
    return Supplier.objects.create(name=name)


def make_product(sku='SKU-1', name='Test Product'):
    return Product.objects.create(sku=sku, name=name)
