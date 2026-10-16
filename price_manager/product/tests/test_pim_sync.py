from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.postgres.search import SearchQuery
from django.test import TestCase
from pim_api import Entity, SiteAPI

from product.models import Brand, Category, Product
from product.services.pim_sync import (
    _fetch_pim_category,
    _fetch_pim_link,
    _fetch_pim_product,
    load_products_by_number,
    sync_product_from_pim,
)


LINK_PATCH = 'product.services.pim_sync._fetch_pim_link'
PRODUCT_PATCH = 'product.services.pim_sync._fetch_pim_product'
CATEGORY_PATCH = 'product.services.pim_sync._fetch_pim_category'


class PimClientWiringTests(TestCase):
    """Below the _fetch_pim_* seam: confirms these actually build the right
    Entity and hand it to pim_client.site.get — the two-line layer every
    other test in this module mocks past.
    """

    def test_fetch_pim_link_calls_site_with_price_manager_product_entity(self):
        with patch.object(SiteAPI, 'get', return_value={'number': 'N1'}) as mock_get:
            _fetch_pim_link('pmp123')

        method = mock_get.call_args[0][0]
        self.assertIsInstance(method, Entity)
        self.assertEqual(method.name, 'PriceManagerProduct')
        self.assertEqual(method.id, 'pmp123')

    def test_fetch_pim_product_calls_site_with_product_entity(self):
        with patch.object(SiteAPI, 'get', return_value={'number': 'N1'}) as mock_get:
            _fetch_pim_product('abc123')

        method = mock_get.call_args[0][0]
        self.assertIsInstance(method, Entity)
        self.assertEqual(method.name, 'Product')
        self.assertEqual(method.id, 'abc123')

    def test_fetch_pim_category_calls_site_with_category_entity(self):
        with patch.object(SiteAPI, 'get', return_value={'name': 'Cat'}) as mock_get:
            _fetch_pim_category('cat123')

        method = mock_get.call_args[0][0]
        self.assertIsInstance(method, Entity)
        self.assertEqual(method.name, 'Category')
        self.assertEqual(method.id, 'cat123')


class SyncProductFromPimTests(TestCase):
    """sync_product_from_pim takes a PriceManagerProduct id and reads the PIM
    Product through its productId.

    Every assertion below re-reads the row with `Product.objects.get(pk=...)`
    instead of inspecting the instance `sync_product_from_pim` returned. A fresh
    instance carries only real columns, so assigning to an attribute that is not
    a field — as this module did with `category_path`, which `save()` silently
    discarded — can no longer make a test pass.
    """

    def _sync(self, product_payload, link=None, pim_id='pmp-1'):
        link = link if link is not None else {'id': pim_id, 'number': 'N1', 'productId': 'prod-1'}
        with patch(LINK_PATCH, return_value=link), \
                patch(PRODUCT_PATCH, return_value=product_payload) as fetch_product:
            product = sync_product_from_pim(pim_id)
        return Product.objects.get(pk=product.pk), fetch_product

    def test_creates_the_product_from_the_link_and_its_pim_product(self):
        payload = {'number': 'PIM-NUMBER', 'name': 'Товар 1', 'categoriesIds': []}

        saved, fetch_product = self._sync(payload)

        fetch_product.assert_called_once_with('prod-1')
        self.assertEqual(saved.pim_id, 'pmp-1')
        self.assertEqual(saved.number, 'N1')
        self.assertEqual(saved.name, 'Товар 1')
        self.assertEqual(saved.raw_data, payload)
        self.assertEqual(saved.categories.count(), 0)

    def test_resync_updates_existing_row_and_never_touches_number(self):
        existing = Product.objects.create(pim_id='pmp-1', number='LOCAL-SKU', name='Old')

        with patch(LINK_PATCH) as fetch_link:
            sync_product_from_pim('pmp-1', data={'number': 'OTHER', 'name': 'New', 'categoriesIds': []})
            fetch_link.assert_not_called()

        self.assertEqual(Product.objects.filter(pim_id='pmp-1').count(), 1)
        saved = Product.objects.get(pk=existing.pk)
        self.assertEqual(saved.name, 'New')
        self.assertEqual(saved.number, 'LOCAL-SKU')

    def test_unlinked_product_with_the_links_number_adopts_it(self):
        waiting = Product.objects.create(number='N1')

        saved, _ = self._sync({'name': 'Товар', 'categoriesIds': []})

        self.assertEqual(saved.pk, waiting.pk)
        self.assertEqual(saved.pim_id, 'pmp-1')
        self.assertEqual(Product.objects.count(), 1)

    def test_unlinked_product_with_a_case_variant_number_adopts_it(self):
        # number's uniqueness is case-insensitive: a differently-cased match
        # is the same Product, not grounds for a second row.
        waiting = Product.objects.create(number='n1')

        saved, _ = self._sync({'name': 'Товар', 'categoriesIds': []})

        self.assertEqual(saved.pk, waiting.pk)
        self.assertEqual(saved.pim_id, 'pmp-1')
        self.assertEqual(Product.objects.count(), 1)

    def test_link_without_product_id_saves_the_link_only(self):
        with patch(LINK_PATCH, return_value={'id': 'pmp-1', 'number': 'N1', 'productId': None}), \
                patch(PRODUCT_PATCH) as fetch_product:
            product = sync_product_from_pim('pmp-1')

        fetch_product.assert_not_called()
        saved = Product.objects.get(pk=product.pk)
        self.assertEqual((saved.pim_id, saved.number, saved.name), ('pmp-1', 'N1', None))

    def test_failed_link_fetch_leaves_no_row(self):
        with patch(LINK_PATCH, side_effect=RuntimeError('pim down')):
            with self.assertRaises(RuntimeError):
                sync_product_from_pim('pmp-1')

        self.assertEqual(Product.objects.count(), 0)

    def test_resolves_single_category_with_parent_walk(self):
        product_payload = {'number': 'N1', 'name': 'Товар', 'categoriesIds': ['cat-child']}

        def fake_category(pim_category_id):
            if pim_category_id == 'cat-child':
                return {'name': 'Телефоны', 'parentsIds': ['cat-root']}
            if pim_category_id == 'cat-root':
                return {'name': 'Электроника', 'parentsIds': []}
            raise AssertionError(f'unexpected category id {pim_category_id}')

        with patch(CATEGORY_PATCH, side_effect=fake_category):
            saved, _ = self._sync(product_payload)

        self.assertEqual(saved.categories.count(), 1)
        category = saved.categories.get()
        self.assertEqual(category.pim_id, 'cat-child')
        self.assertEqual(category.parent.pim_id, 'cat-root')

        # PIM's payload carries no path string, so the linked Category's MPTT
        # ancestry is the only place a category path can come from.
        self.assertEqual(
            [c.name for c in category.get_ancestors(include_self=True)],
            ['Электроника', 'Телефоны'],
        )

        # Ancestor was created too, and is linked in the tree.
        self.assertEqual(Category.objects.filter(pim_id='cat-root').count(), 1)

    def test_multiple_categories_are_all_linked(self):
        product_payload = {'number': 'N1', 'name': 'Товар', 'categoriesIds': ['a', 'b']}

        def fake_category(pim_category_id):
            return {'name': f'Категория {pim_category_id.upper()}', 'parentsIds': []}

        with patch(CATEGORY_PATCH, side_effect=fake_category):
            saved, _ = self._sync(product_payload)

        self.assertEqual(
            sorted(saved.categories.values_list('name', flat=True)),
            ['Категория A', 'Категория B'],
        )

    def test_unresolvable_category_is_skipped_not_fatal(self):
        product_payload = {'number': 'N1', 'name': 'Товар', 'categoriesIds': ['bad-id']}

        with patch(CATEGORY_PATCH, side_effect=RuntimeError('pim down')):
            saved, _ = self._sync(product_payload)

        self.assertEqual(saved.categories.count(), 0)
        # The product itself still persisted — one bad id doesn't abort the sync.
        self.assertEqual(saved.name, 'Товар')

    def test_the_soft_time_limit_is_not_an_unresolvable_category(self):
        # Celery's soft limit is an Exception too; skipped like a bad id, it
        # would leave the batch running into the hard limit's SIGKILL.
        product_payload = {'number': 'N1', 'name': 'Товар', 'categoriesIds': ['cat-1']}

        with patch(CATEGORY_PATCH, side_effect=SoftTimeLimitExceeded()):
            with self.assertRaises(SoftTimeLimitExceeded):
                self._sync(product_payload)

    def test_brand_is_created_from_brand_id_and_linked(self):
        payload = {'number': 'N1', 'name': 'Товар', 'brandId': 'br-1', 'brandName': 'Grohe'}

        saved, _ = self._sync(payload)

        self.assertIsNotNone(saved.brand)
        self.assertEqual(saved.brand.pim_id, 'br-1')
        self.assertEqual(saved.brand.name, 'Grohe')

    def test_brand_is_matched_on_id_so_a_rename_does_not_fork_it(self):
        """PIM-овский brandId — ссылка на сущность; имя это лишь подпись.

        Сопоставление по имени раскололо бы один бренд надвое при первом же
        переименовании в PIM.
        """
        self._sync({'number': 'N1', 'brandId': 'br-1', 'brandName': 'Grohe'}, pim_id='pmp-1')
        saved, _ = self._sync(
            {'number': 'N2', 'brandId': 'br-1', 'brandName': 'GROHE AG'},
            link={'id': 'pmp-2', 'number': 'N2', 'productId': 'prod-2'},
            pim_id='pmp-2',
        )

        self.assertEqual(Brand.objects.count(), 1)
        self.assertEqual(saved.brand.name, 'GROHE AG')

    def test_product_without_brand_id_keeps_brand_null(self):
        saved, _ = self._sync({'number': 'N1', 'name': 'Товар'})

        self.assertIsNone(saved.brand)
        self.assertEqual(Brand.objects.count(), 0)

    def test_sync_rebuilds_the_search_vector(self):
        payload = {'number': 'N1', 'name': 'Смеситель', 'categoriesIds': []}

        saved, _ = self._sync(payload)

        self.assertIsNotNone(saved.search_vector)
        self.assertTrue(
            Product.objects.filter(
                pk=saved.pk, search_vector=SearchQuery('смеситель', config='russian')
            ).exists()
        )


def _pim_pages(*rows):
    """site.get каталога PIM: отдаёт rows страницами по offset/maxSize запроса."""
    def get(query, timeout=None):
        return {'total': len(rows), 'list': list(rows[query.offset:query.offset + query.maxSize])}
    return get


class LoadProductsByNumberTests(TestCase):
    """load_products_by_number: товар PIM ложится на локальный Product с тем же
    номером без учёта регистра, если номер у нас ровно у одного товара."""

    def setUp(self):
        self.bosch = Brand.objects.create(pim_id='br-bosch', name='Bosch')
        self.makita = Brand.objects.create(pim_id='br-makita', name='Makita')

    def _load(self, *rows, page_size=1000):
        with patch.object(SiteAPI, 'get', side_effect=_pim_pages(*rows)):
            return load_products_by_number(page_size=page_size)

    def test_a_case_variant_fills_the_local_product(self):
        category = Category.objects.create(pim_id='cat-1', name='Дрели')
        product = Product.objects.create(number='abc-1')

        stats = self._load({'id': 'p-1', 'number': 'ABC-1', 'name': 'Дрель', 'categoriesIds': ['cat-1']})

        saved = Product.objects.get(pk=product.pk)
        self.assertEqual(saved.name, 'Дрель')
        self.assertEqual(saved.raw_data['id'], 'p-1')
        self.assertEqual(list(saved.categories.all()), [category])
        self.assertEqual((stats['matched'], stats['skipped']), (1, 0))

    def test_a_number_two_products_hold_in_any_case_is_skipped(self):
        # Без бренда «ABC-1» и Bosch «abc-1» — разные товары. Бренд Bosch на
        # первом нарушил бы уникальность пары у второго.
        brandless = Product.objects.create(number='ABC-1')
        branded = Product.objects.create(number='abc-1', brand=self.bosch)

        stats = self._load({'id': 'p-1', 'number': 'ABC-1', 'name': 'Дрель', 'brandId': 'br-bosch'})

        self.assertEqual((stats['matched'], stats['skipped']), (0, 1))
        for product, brand in ((brandless, None), (branded, self.bosch)):
            saved = Product.objects.get(pk=product.pk)
            self.assertEqual(saved.raw_data, {})
            self.assertEqual(saved.brand, brand)

    def test_the_exact_case_wins_whatever_the_page_order(self):
        upper = {'id': 'p-upper', 'number': 'ABC-1'}
        exact = {'id': 'p-exact', 'number': 'abc-1'}
        for rows in ((upper, exact), (exact, upper)):
            for page_size in (1, 1000):
                with self.subTest(order=[row['id'] for row in rows], page_size=page_size):
                    Product.objects.all().delete()
                    product = Product.objects.create(number='abc-1')

                    stats = self._load(*rows, page_size=page_size)

                    self.assertEqual(Product.objects.get(pk=product.pk).raw_data['id'], 'p-exact')
                    self.assertEqual((stats['matched'], stats['skipped']), (1, 1))

    def test_the_products_brand_wins_over_the_exact_case(self):
        product = Product.objects.create(number='abc-1', brand=self.bosch)

        self._load({'id': 'p-makita', 'number': 'abc-1', 'brandId': 'br-makita'},
                   {'id': 'p-bosch', 'number': 'ABC-1', 'brandId': 'br-bosch'})

        saved = Product.objects.get(pk=product.pk)
        self.assertEqual(saved.raw_data['id'], 'p-bosch')
        self.assertEqual(saved.brand, self.bosch)

    def test_a_brandless_product_takes_the_pim_brand(self):
        product = Product.objects.create(number='D-1')

        self._load({'id': 'p-1', 'number': 'D-1', 'brandId': 'br-new', 'brandName': 'Новый'})

        self.assertEqual(Product.objects.get(pk=product.pk).brand.name, 'Новый')

    def test_pim_without_a_brand_keeps_the_local_one(self):
        product = Product.objects.create(number='D-1', brand=self.bosch)

        self._load({'id': 'p-1', 'number': 'D-1', 'name': 'Дрель'})

        saved = Product.objects.get(pk=product.pk)
        self.assertEqual(saved.brand, self.bosch)
        self.assertEqual(saved.name, 'Дрель')

    def test_a_brand_not_from_pim_is_kept_when_pim_disagrees(self):
        product = Product.objects.create(number='D-1', brand=self.bosch)

        self._load({'id': 'p-1', 'number': 'D-1', 'name': 'Дрель', 'brandId': 'br-makita'})

        saved = Product.objects.get(pk=product.pk)
        self.assertEqual(saved.brand, self.bosch)
        # Остальное из PIM записано: отказ — только в бренде.
        self.assertEqual(saved.name, 'Дрель')

    def test_a_brand_pim_gave_follows_pim(self):
        product = Product.objects.create(number='D-1', brand=self.bosch,
                                         raw_data={'id': 'p-1', 'brandId': 'br-bosch'})

        self._load({'id': 'p-1', 'number': 'D-1', 'brandId': 'br-makita'})

        self.assertEqual(Product.objects.get(pk=product.pk).brand, self.makita)

    def test_the_soft_time_limit_is_not_retried(self):
        # Повтор страницы — для обрыва связи. Мягкий лимит Celery повтором
        # только проспал бы минуту до жёсткого.
        with patch.object(SiteAPI, 'get', side_effect=SoftTimeLimitExceeded()) as get, \
                patch('product.services.pim_sync.time.sleep') as sleep:
            with self.assertRaises(SoftTimeLimitExceeded):
                load_products_by_number()

        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()
