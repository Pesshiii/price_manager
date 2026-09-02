from supplier.models import Supplier
from pricing.models import PriceType


def make_price_type(name='закупочная', label='Закупочная'):
    return PriceType.objects.create(name=name, label=label)


def make_supplier(name='Test Supplier'):
    return Supplier.objects.create(name=name)
