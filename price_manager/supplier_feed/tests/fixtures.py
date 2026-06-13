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


def make_feed_mapping(supplier=None, name='Прайс', supplier_sku_column='article',
                      name_column='name', low_match_threshold=0.5, **kwargs):
    if supplier is None:
        supplier = make_supplier()
    if 'dataframe' not in kwargs:
        kwargs['dataframe'] = make_dataframe()
    return FeedMapping.objects.create(
        supplier=supplier,
        name=name,
        supplier_sku_column=supplier_sku_column,
        name_column=name_column,
        low_match_threshold=low_match_threshold,
        **kwargs,
    )


class InMemoryCandidateFinder:
    """In-memory test double for the pg_trgm finder.

    Filters a pre-loaded candidate list by score threshold so tests need no DB
    query and no patch() call — just pass an instance as finder= to run_matching.
    """

    def __init__(self, candidates: list[dict]):
        self._candidates = candidates

    def __call__(self, name: str, low_thresh: float) -> list[dict]:
        return [c for c in self._candidates if c['score'] >= low_thresh]


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
