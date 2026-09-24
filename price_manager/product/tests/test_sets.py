from contextlib import ExitStack
from unittest.mock import patch

from django.test import TestCase
from pim_api import EntityList, ListResult, SiteAPI

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from product.models import Product, ProductSetItem
from product.services import sets
from product.services.sets import sync_product_sets

MODULE = 'product.services.sets'


class SyncProductSetsTests(TestCase):
    """PIM подменён на пяти швах services/sets.py. Каждый тест описывает PIM
    словарями: связи набор→компонент, товары PIM, PMP (id товара PIM -> наши pk).

    Состояние проверяется перечитыванием из базы, а не по возвращённым
    объектам — тот же принцип, что в test_pim_sync.py.
    """

    SET = 'pim-set'

    def setUp(self):
        self.supplier = Supplier.objects.create(name='Поставщик')
        self.links = []
        self.pim_products = {
            self.SET: {'id': self.SET, 'number': 'SET-1', 'name': 'Набор электрика', 'categoriesIds': []},
        }
        self.platform_ids = {}

    def _link(self, component, amount=1, sorting=0, set_id=None):
        self.links.append({
            'associatingItemId': set_id or self.SET, 'associatedItemId': component,
            'amount': amount, 'sorting': sorting,
        })

    def _pim_component(self, pim_id, number, name=None):
        self.pim_products[pim_id] = {'id': pim_id, 'number': number, 'name': name or number}

    def _local(self, number, stock=None):
        product = Product.objects.create(number=number, name=number)
        if stock is not None:
            MainProduct.objects.create(product=product, supplier=self.supplier,
                                       article=number, name=number, stock=stock)
        return product

    def _sync(self, association_id='assoc-1'):
        def fetch_product(pim_id):
            return self.pim_products[pim_id]

        with ExitStack() as stack:
            stack.enter_context(patch(f'{MODULE}._fetch_set_association_id', return_value=association_id))
            stack.enter_context(patch(f'{MODULE}._fetch_set_links', return_value=self.links))
            stack.enter_context(patch(f'{MODULE}._fetch_pim_products_brief', return_value=self.pim_products))
            stack.enter_context(patch(f'{MODULE}._fetch_platform_ids', return_value=self.platform_ids))
            stack.enter_context(patch(f'{MODULE}._fetch_pim_product', side_effect=fetch_product))
            return sync_product_sets()

    def _set(self):
        return Product.objects.get(number='SET-1')

    def _items(self, product=None):
        return list(ProductSetItem.objects.filter(set_product=product or self._set()).order_by('sorting', 'pk'))

    def test_creates_the_set_product_and_its_composition(self):
        stand = self._local('ST-1', stock=10)
        shelf = self._local('SH-1', stock=3)
        self._pim_component('c-stand', 'ST-1', 'Стойка')
        self._pim_component('c-shelf', 'SH-1', 'Полка')
        self._link('c-stand', amount=4, sorting=0)
        self._link('c-shelf', amount=4, sorting=10)

        stats = self._sync()

        product = self._set()
        self.assertIsNone(product.pim_id)
        self.assertEqual(product.name, 'Набор электрика')
        self.assertEqual(product.raw_data['number'], 'SET-1')
        items = self._items(product)
        self.assertEqual([(i.component_id, i.amount) for i in items], [(stand.pk, 4), (shelf.pk, 4)])
        self.assertEqual(items[0].component_name, 'Стойка')
        self.assertEqual(stats['created_sets'], 1)
        self.assertEqual(stats['items'], 2)

    def test_second_run_is_idempotent(self):
        self._local('ST-1', stock=1)
        self._pim_component('c-stand', 'ST-1')
        self._link('c-stand', amount=2)

        self._sync()
        stats = self._sync()

        self.assertEqual(Product.objects.filter(number__iexact='SET-1').count(), 1)
        self.assertEqual(len(self._items()), 1)
        self.assertEqual(stats['created_sets'], 0)

    def test_set_already_linked_through_pmp_is_reused(self):
        existing = Product.objects.create(number='OLD-NUMBER', pim_id='pmp-9')
        self.platform_ids[self.SET] = [existing.pk]
        self._pim_component('c-1', 'C-1')
        self._link('c-1')

        self._sync()

        self.assertEqual(ProductSetItem.objects.get().set_product_id, existing.pk)
        self.assertFalse(Product.objects.filter(number='SET-1').exists())

    def test_set_is_matched_by_number_case_insensitively(self):
        existing = Product.objects.create(number='set-1')
        self._pim_component('c-1', 'C-1')
        self._link('c-1')

        self._sync()

        self.assertEqual(ProductSetItem.objects.get().set_product_id, existing.pk)
        self.assertEqual(Product.objects.count(), 1)

    def test_set_without_a_name_in_pim_falls_back_to_its_number(self):
        self.pim_products[self.SET]['name'] = ''
        self._pim_component('c-1', 'C-1')
        self._link('c-1')

        self._sync()

        self.assertEqual(self._set().name, 'SET-1')

    def test_unresolved_component_is_kept_as_a_snapshot(self):
        self._pim_component('c-missing', 'NOPE-1', 'Блокнот')
        self._link('c-missing')

        stats = self._sync()

        item = ProductSetItem.objects.get()
        self.assertIsNone(item.component)
        self.assertEqual((item.component_number, item.component_name), ('NOPE-1', 'Блокнот'))
        self.assertEqual(stats['unresolved_components'], 1)

    def test_component_prefers_the_pmp_linked_product(self):
        by_number = self._local('C-1', stock=5)
        linked = self._local('C-1-LINKED')
        self.platform_ids['c-1'] = [linked.pk]
        self._pim_component('c-1', 'C-1')
        self._link('c-1')

        self._sync()

        self.assertEqual(ProductSetItem.objects.get().component_id, linked.pk)
        self.assertNotEqual(linked.pk, by_number.pk)

    def test_among_several_pmp_links_the_one_with_stock_wins(self):
        empty = self._local('C-A', stock=0)
        stocked = self._local('C-B', stock=7)
        self.platform_ids['c-1'] = [empty.pk, stocked.pk]
        self._pim_component('c-1', 'C-X')
        self._link('c-1')

        self._sync()

        self.assertEqual(ProductSetItem.objects.get().component_id, stocked.pk)

    def test_empty_amount_means_one_and_non_positive_is_skipped(self):
        self._pim_component('c-1', 'C-1')
        self._pim_component('c-2', 'C-2')
        self._link('c-1', amount=None)
        self._link('c-2', amount=0)

        stats = self._sync()

        self.assertEqual([(i.component_pim_product_id, i.amount) for i in self._items()], [('c-1', 1)])
        self.assertEqual(stats['skipped_links'], 1)

    def test_component_removed_in_pim_disappears_from_the_set(self):
        self._pim_component('c-1', 'C-1')
        self._pim_component('c-2', 'C-2')
        self._link('c-1')
        self._link('c-2')
        self._sync()

        self.links = [link for link in self.links if link['associatedItemId'] == 'c-1']
        self._sync()

        self.assertEqual([i.component_pim_product_id for i in self._items()], ['c-1'])

    def test_set_gone_from_pim_loses_its_composition_but_keeps_the_product(self):
        self._pim_component('c-1', 'C-1')
        self._link('c-1')
        self._sync()

        self.links = []
        stats = self._sync()

        self.assertTrue(Product.objects.filter(number='SET-1').exists())
        self.assertFalse(ProductSetItem.objects.exists())
        self.assertEqual(stats['pruned_sets'], 1)

    def test_a_failed_set_blocks_pruning(self):
        self._pim_component('c-1', 'C-1')
        self._link('c-1')
        self._sync()

        other = 'pim-set-2'
        self.links = [{'associatingItemId': other, 'associatedItemId': 'c-1', 'amount': 1, 'sorting': 0}]
        stats = self._sync()  # other отсутствует в self.pim_products -> KeyError при чтении

        self.assertEqual(stats['failed_sets'], 1)
        self.assertEqual(len(self._items()), 1)

    def test_set_without_number_and_pmp_is_skipped_not_created(self):
        self.pim_products[self.SET]['number'] = None
        self._pim_component('c-1', 'C-1')
        self._link('c-1')

        stats = self._sync()

        self.assertEqual(stats['skipped_sets'], 1)
        self.assertFalse(ProductSetItem.objects.exists())
        self.assertEqual(Product.objects.count(), 0)

    def test_missing_association_changes_nothing(self):
        stats = self._sync(association_id=None)

        self.assertEqual(stats['sets'], 0)
        self.assertEqual(Product.objects.count(), 0)


class FetchAllTests(TestCase):
    def test_truncated_listing_raises_instead_of_shortening_sets(self):
        truncated = ListResult(total=5, items=[{}], truncated=True)
        with patch(f'{MODULE}.fetch_list', return_value=truncated):
            with self.assertRaises(RuntimeError):
                sets._fetch_all(EntityList(name='AssociatedProduct'))

    def test_platform_ids_are_grouped_by_pim_product(self):
        page = {'total': 3, 'list': [
            {'productId': 'p1', 'platformID': '10'},
            {'productId': 'p1', 'platformID': '11'},
            {'productId': 'p2', 'platformID': 'not-a-pk'},
        ]}
        with patch.object(SiteAPI, 'get', return_value=page):
            found = sets._fetch_platform_ids(['p1', 'p2'])

        self.assertEqual(dict(found), {'p1': [10, 11]})
