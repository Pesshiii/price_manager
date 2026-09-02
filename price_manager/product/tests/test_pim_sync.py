from unittest.mock import patch

from django.test import TestCase
from pim_api import Entity, SiteAPI

from product.models import Category, Product
from product.services.pim_sync import _fetch_pim_category, _fetch_pim_product, sync_product_from_pim


PRODUCT_PATCH = 'product.services.pim_sync._fetch_pim_product'
CATEGORY_PATCH = 'product.services.pim_sync._fetch_pim_category'


class PimClientWiringTests(TestCase):
    """Below the _fetch_pim_* seam: confirms these actually build the right
    Entity and hand it to pim_client.site.get — the two-line layer every
    other test in this module mocks past.
    """

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
    def test_create_with_no_categories(self):
        payload = {'number': 'N1', 'name': 'Товар 1', 'categoriesIds': []}
        with patch(PRODUCT_PATCH, return_value=payload):
            product = sync_product_from_pim('pim-1')

        self.assertEqual(product.pim_id, 'pim-1')
        self.assertEqual(product.number, 'N1')
        self.assertEqual(product.name, 'Товар 1')
        self.assertEqual(product.raw_data, payload)
        self.assertEqual(product.category_path, '')
        self.assertEqual(product.categories.count(), 0)

    def test_resync_updates_existing_row_not_duplicate(self):
        with patch(PRODUCT_PATCH, return_value={'number': 'N1', 'name': 'Old', 'categoriesIds': []}):
            sync_product_from_pim('pim-1')

        with patch(PRODUCT_PATCH, return_value={'number': 'N1', 'name': 'New', 'categoriesIds': []}):
            product = sync_product_from_pim('pim-1')

        self.assertEqual(Product.objects.filter(pim_id='pim-1').count(), 1)
        self.assertEqual(product.name, 'New')

    def test_resolves_single_category_with_parent_walk(self):
        product_payload = {'number': 'N1', 'name': 'Товар', 'categoriesIds': ['cat-child']}

        def fake_category(pim_category_id):
            if pim_category_id == 'cat-child':
                return {'name': 'Телефоны', 'parentsIds': ['cat-root']}
            if pim_category_id == 'cat-root':
                return {'name': 'Электроника', 'parentsIds': []}
            raise AssertionError(f'unexpected category id {pim_category_id}')

        with patch(PRODUCT_PATCH, return_value=product_payload), \
                patch(CATEGORY_PATCH, side_effect=fake_category):
            product = sync_product_from_pim('pim-1')

        self.assertEqual(product.categories.count(), 1)
        category = product.categories.get()
        self.assertEqual(category.pim_id, 'cat-child')
        self.assertEqual(category.parent.pim_id, 'cat-root')
        self.assertEqual(product.category_path, 'Электроника > Телефоны')

        # Ancestor was created too, and is linked in the tree.
        self.assertEqual(Category.objects.filter(pim_id='cat-root').count(), 1)

    def test_category_path_joins_multiple_categories(self):
        product_payload = {'number': 'N1', 'name': 'Товар', 'categoriesIds': ['a', 'b']}

        def fake_category(pim_category_id):
            return {'name': f'Категория {pim_category_id.upper()}', 'parentsIds': []}

        with patch(PRODUCT_PATCH, return_value=product_payload), \
                patch(CATEGORY_PATCH, side_effect=fake_category):
            product = sync_product_from_pim('pim-1')

        self.assertEqual(product.categories.count(), 2)
        self.assertEqual(product.category_path, 'Категория A; Категория B')

    def test_unresolvable_category_is_skipped_not_fatal(self):
        product_payload = {'number': 'N1', 'name': 'Товар', 'categoriesIds': ['bad-id']}

        with patch(PRODUCT_PATCH, return_value=product_payload), \
                patch(CATEGORY_PATCH, side_effect=RuntimeError('pim down')):
            product = sync_product_from_pim('pim-1')

        self.assertEqual(product.categories.count(), 0)
        self.assertEqual(product.category_path, '')

    def test_accepts_prefetched_data_without_calling_fetch(self):
        payload = {'number': 'N1', 'name': 'Товар', 'categoriesIds': []}
        with patch(PRODUCT_PATCH) as mock_fetch:
            product = sync_product_from_pim('pim-1', data=payload)
            mock_fetch.assert_not_called()
        self.assertEqual(product.number, 'N1')
