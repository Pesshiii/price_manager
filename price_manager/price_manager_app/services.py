import math

from django.db.models import Q
from django.utils import timezone

from main_price.models import MainProduct
from price_manager_app.models import PriceManager
from supplier_manager.models import SupplierProduct, SP_PRICES


def get_price_query(price_from, price_to, price_prefix):
    if price_from and price_to:
        return Q(**{f'{price_prefix}__range': (price_from, price_to)})
    if price_from:
        return Q(**{f'{price_prefix}__gte': price_from})
    if price_to:
        return Q(**{f'{price_prefix}__lte': price_to})
    return Q()


def apply_price_manager(price_manager: PriceManager):
    products = SupplierProduct.objects.filter(supplier=price_manager.supplier)
    if price_manager.has_rrp is not None:
        if price_manager.has_rrp:
            products = products.filter(rrp__gt=0)
        else:
            products = products.filter(rrp=0)
    discounts = list(price_manager.discounts.values_list('id', flat=True))
    if discounts:
        products = products.filter(discounts__in=discounts)
    if price_manager.source in SP_PRICES:
        products = products.filter(
            get_price_query(price_manager.price_from, price_manager.price_to, price_manager.source)
        )
    else:
        products = products.filter(
            get_price_query(
                price_manager.price_from,
                price_manager.price_to,
                f'main_product__{price_manager.source}',
            )
        )
    mps = []
    for product in products:
        main_product = product.main_product
        if not main_product:
            continue
        main_product.price_managers.add(price_manager)
        source_object = product if price_manager.source in SP_PRICES else main_product
        base_value = getattr(source_object, price_manager.source, 0)
        calculated_value = math.ceil(
            base_value * main_product.supplier.currency.value * (1 + price_manager.markup / 100)
            + price_manager.increase
        )
        setattr(main_product, price_manager.dest, calculated_value)
        main_product.price_updated_at = timezone.now()
        mps.append(main_product)
    MainProduct.objects.bulk_update(mps, fields=[price_manager.dest, 'price_updated_at'])
