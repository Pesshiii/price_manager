from django.test import TestCase



from supplier_manager.models import Currency, Supplier
from supplier_product_manager.models import SupplierProduct
from product.models import Product as PimProduct
from .models import MainProduct, MainProductLog
from .utils import update_stocks


class UpdateStocksNullSafeTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Stock supplier',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )

    def test_updates_from_null_to_zero(self):
        mp = MainProduct.objects.create(
            supplier=self.supplier,
            article='ST-1',
            name='Null to zero',
            stock=None,
        )
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='SP-ST-1',
            name='Stock row',
            stock=None,
        )

        updated_count = update_stocks()

        mp.refresh_from_db()
        self.assertEqual(updated_count, 1)
        self.assertEqual(mp.stock, 0)
        self.assertTrue(MainProductLog.objects.filter(main_product=mp, stock=0).exists())

    def test_second_run_is_a_no_op(self):
        """Once a stock is synced, re-running must not re-count or re-log it.

        The NULL -> 0 transition is picked up by an explicit stock__isnull
        branch, so this guards that the branch stops matching after the first
        run instead of firing on every run.
        """
        mp = MainProduct.objects.create(
            supplier=self.supplier,
            article='ST-3',
            name='Null to zero once',
            stock=None,
        )
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='SP-ST-3',
            name='Stock row',
            stock=None,
        )

        self.assertEqual(update_stocks(), 1)
        logs_after_first_run = MainProductLog.objects.filter(main_product=mp).count()

        self.assertEqual(update_stocks(), 0)
        self.assertEqual(MainProductLog.objects.filter(main_product=mp).count(), logs_after_first_run)


    def test_updates_from_positive_to_zero(self):
        mp = MainProduct.objects.create(
            supplier=self.supplier,
            article='ST-2',
            name='Positive to zero',
            stock=7,
        )
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='SP-ST-2',
            name='Stock row',
            stock=None,
        )

        updated_count = update_stocks()

        mp.refresh_from_db()
        self.assertEqual(updated_count, 1)
        self.assertEqual(mp.stock, 0)
        self.assertTrue(MainProductLog.objects.filter(main_product=mp, stock=0).exists())


class UpdateStocksBatchingTests(TestCase):
    """update_stocks walks the catalog in pk chunks of `batch_size`.

    UpdateStocksNullSafeTests cannot cover that: each of those creates a single
    MainProduct, so the loop runs exactly one iteration whether or not it
    really batches. These pass a batch_size small enough to need several.
    """

    def setUp(self):
        self.currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Batch supplier',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )

    def _product_with_stock(self, index, stock):
        mp = MainProduct.objects.create(
            supplier=self.supplier,
            article=f'BT-{index}',
            name=f'Batched {index}',
            stock=None,
        )
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article=f'SP-BT-{index}',
            name='Stock row',
            stock=stock,
        )
        return mp

    def test_every_batch_is_updated_and_logged(self):
        """Distinct stock per product, so a chunk-scoping slip shows up in the
        logs rather than hiding behind matching counts."""
        products = [self._product_with_stock(i, i) for i in range(1, 6)]

        self.assertEqual(update_stocks(batch_size=2), 5)

        for expected, mp in enumerate(products, start=1):
            mp.refresh_from_db()
            self.assertEqual(mp.stock, expected)
            self.assertEqual(
                list(MainProductLog.objects.filter(main_product=mp).values_list('stock', flat=True)),
                [expected],
            )
        self.assertEqual(MainProductLog.objects.count(), 5)

    def test_pk_gap_does_not_drop_the_tail(self):
        """Chunk bounds come from real pks, not offsets over count().

        A deleted product leaves count() < max(pk), which is exactly when
        offset-derived pk ranges stop short and silently skip the highest pks.
        """
        products = [self._product_with_stock(i, i) for i in range(1, 6)]
        products.pop(2).delete()

        self.assertEqual(update_stocks(batch_size=2), 4)

        for expected, mp in zip([1, 2, 4, 5], products):
            mp.refresh_from_db()
            self.assertEqual(mp.stock, expected)

    def test_one_run_stamps_one_timestamp(self):
        """timezone.now() is read once, above the loop — batching a run must
        not spread it across several stock_updated_at values."""
        for i in range(1, 6):
            self._product_with_stock(i, i)

        update_stocks(batch_size=2)

        stamps = set(MainProduct.objects.values_list('stock_updated_at', flat=True))
        self.assertEqual(len(stamps), 1)

    def test_logs_false_updates_every_batch_without_logging(self):
        """logs=False is the one branch the loop adds statements to without
        bounding a log list, and no caller passes it — both update_stocks_task
        definitions call runner=update_stocks bare, so nothing else covers it.
        """
        for i in range(1, 6):
            self._product_with_stock(i, i)

        self.assertEqual(update_stocks(logs=False, batch_size=2), 5)

        self.assertEqual(MainProductLog.objects.count(), 0)
        self.assertEqual(
            sorted(MainProduct.objects.values_list('stock', flat=True)),
            [1, 2, 3, 4, 5],
        )


from unittest.mock import Mock, patch

import httpx

from django.core.cache import cache
from django.db import transaction
from django.test import override_settings

from core.task_runner import dispatch_after_commit
from . import tasks as mp_tasks
from . import utils as mp_utils
# execute_locked_task's lock lives in the cache; keep it off the shared Redis
# the worker container points at.
LOCMEM_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'dispatch-after-commit-tests',
    }
}


@override_settings(CACHES=LOCMEM_CACHE)
class DispatchAfterCommitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_dispatch_is_held_until_the_transaction_commits(self):
        task = Mock()

        with self.captureOnCommitCallbacks(execute=True):
            dispatch_after_commit(task, 42, keyword='v')
            task.delay.assert_not_called()

        task.delay.assert_called_once_with(42, keyword='v')

    def test_rollback_discards_the_dispatch(self):
        task = Mock()

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                dispatch_after_commit(task)
                raise RuntimeError('runner failed')

        task.delay.assert_not_called()

    def test_each_dispatch_in_a_loop_keeps_its_own_arguments(self):
        # A hand-rolled `lambda: task.delay(pks=pks)` inside a loop would fire
        # every callback with the last batch.
        task = Mock()

        with self.captureOnCommitCallbacks(execute=True):
            for pks in ([1, 2], [3, 4]):
                dispatch_after_commit(task, pks=pks)

        self.assertEqual(
            [call.kwargs['pks'] for call in task.delay.call_args_list],
            [[1, 2], [3, 4]],
        )


@override_settings(CACHES=LOCMEM_CACHE)
class ReindexPimIdsDispatchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Reindex supplier',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )
        self.products = [
            MainProduct.objects.create(
                supplier=self.supplier, article=f'RX-{i}', name=f'Reindex {i}', sku=f'RX-SKU-{i}'
            )
            for i in range(3)
        ]

    def test_batches_dispatch_only_once_the_transaction_commits(self):
        # The batches select Products the task's own transaction just created,
        # so a batch dispatched before the commit would find none of them.
        with patch.object(mp_tasks.reindex_pim_ids_batch_task, 'delay') as delay:
            with self.captureOnCommitCallbacks(execute=True):
                payload = mp_tasks.reindex_pim_ids_task(delay=0, batch_size=2)
                delay.assert_not_called()

            pks = sorted(PimProduct.objects.values_list('pk', flat=True))
            self.assertEqual(len(pks), 3)
            self.assertEqual(
                [call.kwargs['pks'] for call in delay.call_args_list],
                [pks[:2], pks[2:]],
            )

        self.assertEqual(payload['status'], 'success')
        # updated_count is the MainProducts linked, not the batches dispatched.
        self.assertEqual(payload['updated_count'], 3)

    def test_placeholder_claims_its_sku_before_unlinked_products_are_linked(self):
        placeholder = PimProduct.objects.create()
        MainProduct.objects.filter(pk=self.products[0].pk).update(product=placeholder)
        unlinked = MainProduct.objects.create(
            supplier=self.supplier, article='RX-TWIN', name='Twin', sku='RX-SKU-0'
        )

        with patch.object(mp_tasks.reindex_pim_ids_batch_task, 'delay'):
            with self.captureOnCommitCallbacks(execute=True):
                mp_tasks.reindex_pim_ids_task(delay=0)

        unlinked.refresh_from_db()
        placeholder.refresh_from_db()
        self.assertEqual(placeholder.number, 'RX-SKU-0')
        self.assertEqual(unlinked.product_id, placeholder.pk)


from .utils import get_file_url


@override_settings(CACHES=LOCMEM_CACHE)
class GetFileUrlTests(TestCase):
    """get_file_url's fallback chain (#160).

    Every case runs through the real cache path (pim_file:{id}), so LocMem +
    clear() keeps those keys off the shared Redis the worker container points
    at — a leaked key would otherwise answer the next test's lookup.
    """

    def setUp(self):
        cache.clear()

    def _url(self, payload, file_id='file-1', **kwargs):
        with patch('main_product_manager.utils.site') as site:
            site.get.return_value = payload
            return get_file_url(file_id, **kwargs)

    def test_thumbnail_key_is_preferred_and_gets_the_scheme(self):
        url = self._url({'mediumThumbnailUrl': 'pim.test/thumbs/m/1.jpg',
                         'url': 'pim.test/files/1.jpg'})

        self.assertEqual(url, 'https://pim.test/thumbs/m/1.jpg')

    def test_falls_back_to_url_when_thumbnail_key_is_absent(self):
        url = self._url({'url': 'pim.test/files/1.jpg'})

        self.assertEqual(url, 'https://pim.test/files/1.jpg')

    def test_falls_back_to_download_url_as_the_last_key(self):
        # This is the real production payload shape, not a corner case: PIM's
        # File record carries neither a *ThumbnailUrl nor a `url` (checked
        # against the live instance, list and single-record endpoints, every
        # record sampled), so downloadUrl — scheme-less — is the only key that
        # ever resolves and the fallback chain is the whole feature.
        url = self._url({'downloadUrl': 'pim.test/?entryPoint=download&id=1'})

        self.assertEqual(url, 'https://pim.test/?entryPoint=download&id=1')

    def test_returns_none_when_no_key_matches(self):
        self.assertIsNone(self._url({'name': '1.jpg'}))

    def test_empty_thumbnail_is_not_a_url(self):
        url = self._url({'mediumThumbnailUrl': ''})

        self.assertIsNone(url)
        self.assertNotEqual(url, 'https://')

    def test_empty_thumbnail_falls_through_to_the_next_key(self):
        url = self._url({'mediumThumbnailUrl': '', 'url': 'pim.test/files/1.jpg'})

        self.assertEqual(url, 'https://pim.test/files/1.jpg')

    def test_whitespace_only_value_counts_as_missing(self):
        url = self._url({'mediumThumbnailUrl': '   ', 'url': 'pim.test/files/1.jpg'})

        self.assertEqual(url, 'https://pim.test/files/1.jpg')

    def test_absolute_value_is_not_prefixed_twice(self):
        # Which of the three keys PIM sends with a scheme is unverified, so
        # both shapes have to work: https:// stays, http:// is left alone.
        self.assertEqual(
            self._url({'mediumThumbnailUrl': 'https://pim.test/thumbs/m/1.jpg'}),
            'https://pim.test/thumbs/m/1.jpg',
        )
        cache.clear()
        self.assertEqual(
            self._url({'mediumThumbnailUrl': 'http://pim.test/thumbs/m/1.jpg'}),
            'http://pim.test/thumbs/m/1.jpg',
        )

    def test_protocol_relative_value_gets_only_the_scheme(self):
        url = self._url({'mediumThumbnailUrl': '//pim.test/thumbs/m/1.jpg'})

        self.assertEqual(url, 'https://pim.test/thumbs/m/1.jpg')

    def test_root_relative_value_falls_through_instead_of_building_a_bad_url(self):
        url = self._url({'mediumThumbnailUrl': '/upload/thumbs/1.jpg',
                         'downloadUrl': 'https://pim.test/files/1.jpg'})

        self.assertEqual(url, 'https://pim.test/files/1.jpg')

    def test_root_relative_everywhere_degrades_to_none(self):
        self.assertIsNone(self._url({'mediumThumbnailUrl': '/upload/thumbs/1.jpg',
                                     'url': '/upload/1.jpg'}))

    def test_size_argument_picks_the_matching_thumbnail_key(self):
        payload = {'smallThumbnailUrl': 'pim.test/thumbs/s/1.jpg',
                   'mediumThumbnailUrl': 'pim.test/thumbs/m/1.jpg',
                   'largeThumbnailUrl': 'pim.test/thumbs/l/1.jpg'}

        self.assertEqual(self._url(payload, size='small'), 'https://pim.test/thumbs/s/1.jpg')
        cache.clear()
        self.assertEqual(self._url(payload, size='large'), 'https://pim.test/thumbs/l/1.jpg')

    def test_non_string_value_does_not_crash(self):
        url = self._url({'mediumThumbnailUrl': False, 'url': 'pim.test/files/1.jpg'})

        self.assertEqual(url, 'https://pim.test/files/1.jpg')

    def test_null_body_returns_none(self):
        self.assertIsNone(self._url(None))

    def test_non_dict_body_returns_none(self):
        self.assertIsNone(self._url([]))

    def test_cached_non_dict_body_does_not_crash_on_the_next_call(self):
        # The falsy body is cached by the miss branch, so the second call skips
        # the refetch entirely and reaches the tail with a non-dict in hand.
        self._url([])

        with patch('main_product_manager.utils.site') as site:
            self.assertIsNone(get_file_url('file-1'))
            site.get.assert_not_called()

    def test_missing_file_id_never_reaches_pim(self):
        with patch('main_product_manager.utils.site') as site:
            self.assertIsNone(get_file_url(None))
            self.assertIsNone(get_file_url(''))
            site.get.assert_not_called()

    def test_pim_failure_still_degrades_to_none(self):
        with patch('main_product_manager.utils.site') as site:
            site.get.side_effect = RuntimeError('PIM down')

            self.assertIsNone(get_file_url('file-1'))


from . import utils as mp_utils
from .utils import (
    PimScanError,
    _SEARCH_ABSENT,
    _SEARCH_AMBIGUOUS,
    _SEARCH_ERROR,
    _SEARCH_FOUND,
    _link_to_local_product,
    _search_pim_product_id,
    backfill_product_numbers,
    get_pim_data,
    iter_unpushed_product_pk_batches,
    link_to_local_products,
    link_unlinked_main_products,
    push_pim_links,
)


def _pim_list(*ids):
    return {'list': [{'id': pim_id} for pim_id in ids]}


def _created(pim_id):
    return {'status': 'Created', 'stored': True, 'entity': 'PriceManagerProduct', 'id': pim_id}


# Shape of a real rejection: the job ends as Success, the item does not.
_UNIQUE_VIOLATION = {
    'status': 'Failed',
    'stored': False,
    'code': 400,
    'message': 'The record cannot be created due to database constraints: '
               'duplicate key value violates unique constraint',
}


class _PimSearchTestCase(TestCase):
    """Shared fixture for the PIM link code: a supplier plus MainProduct factory."""

    def setUp(self):
        cache.clear()
        self.currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='PIM search supplier',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )

    def product(self, sku='SKU-1', **kwargs):
        # pim_id= — удобство фабрики: связь идёт через FK на product.Product.
        pim_id = kwargs.pop('pim_id', None)
        if pim_id:
            kwargs['product'] = PimProduct.objects.get_or_create(pim_id=pim_id)[0]
        return MainProduct.objects.create(
            supplier=self.supplier,
            article=kwargs.pop('article', f'ART-{sku}'),
            name=kwargs.pop('name', f'Product {sku}'),
            sku=sku,
            **kwargs,
        )


@override_settings(CACHES=LOCMEM_CACHE)
class SearchPimProductIdTests(_PimSearchTestCase):
    """The number search tells an unanswered request apart from every answer."""

    def test_single_match_returns_the_id(self):
        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list('pim-42')
            self.assertEqual(_search_pim_product_id('N-1'), ('pim-42', _SEARCH_FOUND))

    def test_empty_result_is_an_absence(self):
        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list()
            self.assertEqual(_search_pim_product_id('N-1'), (None, _SEARCH_ABSENT))

    def test_several_matches_link_none(self):
        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list('pim-1', 'pim-2')
            self.assertEqual(_search_pim_product_id('AB-1'), (None, _SEARCH_AMBIGUOUS))

    def test_pim_error_is_not_an_answer(self):
        with patch.object(mp_utils, 'site') as site:
            site.get.side_effect = RuntimeError('PIM down')
            self.assertEqual(_search_pim_product_id('N-1'), (None, _SEARCH_ERROR))

    def test_search_uses_equals_so_number_wildcards_stay_literal(self):
        """AtroPIM feeds a `like` value straight into SQL LIKE.

        Measured against the live API: `like '2001_-04_z01'` returns the
        product numbered `20015-04_z01`. PIM numbers routinely carry `_`, so
        under `like` a number can match a *different* product, and exactly
        one wrong match slips past the ambiguity guard. `equals` keeps both
        wildcard characters literal.
        """
        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list('pim-1')
            _search_pim_product_id('2001_-04_z01')
            entity_list = site.get.call_args.args[0]

        self.assertEqual(entity_list.name, 'Product')
        self.assertEqual(
            [(w.attribute, w.type, w.value) for w in entity_list.where],
            [('number', 'equals', '2001_-04_z01')],
        )


class LinkUnlinkedMainProductsTests(_PimSearchTestCase):
    """The local half of reindex: MainProduct -> product.Product by sku = number."""

    def test_creates_one_product_per_sku_and_links_every_main_product_to_it(self):
        first = self.product(sku='SKU-A', name='Первый')
        second = self.product(sku='SKU-A', article='OTHER', name='Второй')

        linked = link_unlinked_main_products()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(linked, 2)
        self.assertEqual(first.product_id, second.product_id)
        self.assertEqual(first.product.number, 'SKU-A')
        self.assertEqual(first.product.name, 'Первый')
        self.assertIsNone(first.product.pim_id)

    def test_links_to_an_existing_product_instead_of_creating_one(self):
        existing = PimProduct.objects.create(number='SKU-B')
        main_product = self.product(sku='SKU-B')

        link_unlinked_main_products()

        main_product.refresh_from_db()
        self.assertEqual(main_product.product_id, existing.pk)
        self.assertEqual(PimProduct.objects.count(), 1)

    def test_existing_links_are_never_moved(self):
        elsewhere = PimProduct.objects.create(number='MANUAL')
        PimProduct.objects.create(number='SKU-C')
        main_product = self.product(sku='SKU-C', product=elsewhere)

        self.assertEqual(link_unlinked_main_products(), 0)

        main_product.refresh_from_db()
        self.assertEqual(main_product.product_id, elsewhere.pk)

    def test_products_without_sku_stay_unlinked(self):
        no_sku = self.product(sku=None, article='NO-SKU')
        empty_sku = self.product(sku='', article='EMPTY-SKU')

        self.assertEqual(link_unlinked_main_products(), 0)

        no_sku.refresh_from_db()
        empty_sku.refresh_from_db()
        self.assertIsNone(no_sku.product_id)
        self.assertIsNone(empty_sku.product_id)
        self.assertEqual(PimProduct.objects.count(), 0)

    def test_sku_longer_than_number_stays_unlinked_without_failing_the_rest(self):
        too_long = self.product(sku='X' * (mp_utils.PRODUCT_NUMBER_MAX_LENGTH + 1))
        fine = self.product(sku='FINE')

        with self.assertLogs(mp_utils.logger, level='WARNING'):
            self.assertEqual(link_unlinked_main_products(batch_size=1), 1)

        too_long.refresh_from_db()
        fine.refresh_from_db()
        self.assertIsNone(too_long.product_id)
        self.assertEqual(fine.product.number, 'FINE')


class BackfillProductNumbersTests(_PimSearchTestCase):
    """Placeholder Products (number NULL) take their MainProducts' sku only when unambiguous."""

    def test_placeholder_takes_the_sku_its_main_products_share(self):
        placeholder = PimProduct.objects.create()
        self.product(sku='SKU-1', product=placeholder)
        self.product(sku='SKU-1', article='OTHER', product=placeholder)

        self.assertEqual(backfill_product_numbers(), 1)

        placeholder.refresh_from_db()
        self.assertEqual(placeholder.number, 'SKU-1')

    def test_disagreeing_skus_leave_the_number_empty(self):
        placeholder = PimProduct.objects.create()
        self.product(sku='SKU-1', product=placeholder)
        self.product(sku='SKU-2', product=placeholder)

        with self.assertLogs(mp_utils.logger, level='WARNING'):
            self.assertEqual(backfill_product_numbers(), 0)

        placeholder.refresh_from_db()
        self.assertIsNone(placeholder.number)

    def test_taken_number_is_not_duplicated(self):
        PimProduct.objects.create(number='SKU-1')
        placeholder = PimProduct.objects.create()
        second = PimProduct.objects.create()
        self.product(sku='SKU-1', product=placeholder)
        self.product(sku='SKU-2', product=second)
        self.product(sku='SKU-2', article='OTHER', product=PimProduct.objects.create())

        with self.assertLogs(mp_utils.logger, level='WARNING'):
            self.assertEqual(backfill_product_numbers(), 1)

        placeholder.refresh_from_db()
        self.assertIsNone(placeholder.number)
        # Two placeholders wanting SKU-2: the lower pk gets it, the other waits.
        second.refresh_from_db()
        self.assertEqual(second.number, 'SKU-2')


class IterUnpushedProductPkBatchesTests(_PimSearchTestCase):
    def test_only_numbered_linked_products_without_pim_id_are_pushed(self):
        waiting = PimProduct.objects.create(number='WAITING')
        self.product(sku='WAITING', product=waiting)
        self.product(sku='WAITING', article='TWICE', product=waiting)
        pushed = PimProduct.objects.create(number='PUSHED', pim_id='pmp-1')
        self.product(sku='PUSHED', product=pushed)
        unnumbered = PimProduct.objects.create()
        self.product(sku='X', product=unnumbered)
        PimProduct.objects.create(number='ORPHAN')

        self.assertEqual(list(iter_unpushed_product_pk_batches()), [[waiting.pk]])


@override_settings(CACHES=LOCMEM_CACHE)
class PushPimLinksTests(_PimSearchTestCase):
    """The PIM half of reindex: search the PIM Product, push the PriceManagerProduct, store its id."""

    def waiting_product(self, number, description=None, **main_product_kwargs):
        product = PimProduct.objects.create(number=number)
        main_product = self.product(sku=number, product=product, **main_product_kwargs)
        if description is not None:
            # Описание живёт в строке прайса поставщика: собственное у
            # MainProduct удалено в Phase 2b.
            SupplierProduct.objects.create(
                main_product=main_product, supplier=self.supplier,
                article=main_product.article, name=main_product.name, description=description,
            )
        return product

    def _site_by_number(self, responses):
        """site.get double for the Product search: number -> response/exception."""
        def get(entity):
            answer = responses[entity.where[0].value]
            if isinstance(answer, Exception):
                raise answer
            return answer
        return get

    def test_found_product_id_goes_into_the_payload_and_the_returned_id_is_stored(self):
        product = self.waiting_product('N-1', name='Дрель', description='Описание')

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, '_upsert_async', return_value=[_created('pmp-1')]) as upsert:
            site.get.side_effect = self._site_by_number({'N-1': _pim_list('pim-product-1')})
            linked = push_pim_links([product.pk], delay=0)

        product.refresh_from_db()
        self.assertEqual(linked, 1)
        self.assertEqual(product.pim_id, 'pmp-1')
        self.assertEqual(upsert.call_args.args[1], [{
            'entity': 'PriceManagerProduct',
            'payload': {
                'platformID': str(product.pk),
                'number': 'N-1',
                'name': 'Дрель',
                'description': 'Описание',
                'productId': 'pim-product-1',
            },
        }])

    def test_absent_and_ambiguous_push_without_the_product_id_key(self):
        # Left out, not null: PIM keeps an existing productId when the key is
        # absent, and a null would clear a link PIM staff set.
        absent = self.waiting_product('ABSENT')
        ambiguous = self.waiting_product('AMBIGUOUS')

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, '_upsert_async', return_value=[_created('pmp-a'), _created('pmp-b')]) as upsert:
            site.get.side_effect = self._site_by_number({
                'ABSENT': _pim_list(),
                'AMBIGUOUS': _pim_list('pim-1', 'pim-2'),
            })
            self.assertEqual(push_pim_links([absent.pk, ambiguous.pk], delay=0), 2)

        payloads = [item['payload'] for item in upsert.call_args.args[1]]
        self.assertEqual([p['number'] for p in payloads], ['ABSENT', 'AMBIGUOUS'])
        self.assertTrue(all('productId' not in p for p in payloads))

    def test_unanswered_search_skips_the_product_and_raises_after_the_writes(self):
        answered = self.waiting_product('ANSWERED')
        errored = self.waiting_product('ERRORED')

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, '_upsert_async', return_value=[_created('pmp-1')]) as upsert:
            site.get.side_effect = self._site_by_number({
                'ANSWERED': _pim_list(),
                'ERRORED': RuntimeError('PIM down'),
            })
            with self.assertRaises(PimScanError):
                push_pim_links([answered.pk, errored.pk], delay=0)

        answered.refresh_from_db()
        errored.refresh_from_db()
        self.assertEqual(answered.pim_id, 'pmp-1')
        self.assertIsNone(errored.pim_id)
        self.assertEqual([i['payload']['number'] for i in upsert.call_args.args[1]], ['ANSWERED'])

    def test_not_modified_answer_is_how_a_lost_id_comes_back(self):
        product = self.waiting_product('N-1')

        with patch.object(mp_utils, 'site') as site, patch.object(mp_utils, '_upsert_async', return_value=[
            {'entity': 'PriceManagerProduct', 'id': 'pmp-lost', 'stored': True, 'status': 'NotModified'},
        ]):
            site.get.side_effect = self._site_by_number({'N-1': _pim_list()})
            push_pim_links([product.pk], delay=0)

        product.refresh_from_db()
        self.assertEqual(product.pim_id, 'pmp-lost')

    def test_rejected_push_takes_over_the_pmp_holding_our_number(self):
        product = self.waiting_product('N-1')
        # The PMP used to belong to another local Product, which loses it.
        previous_owner = PimProduct.objects.create(number='RENUMBERED', pim_id='pmp-taken')

        def site_get(entity):
            if entity.name == 'Product':
                return _pim_list()
            self.assertEqual(entity.name, 'PriceManagerProduct')
            return {'list': [{'id': 'pmp-taken', 'platformID': '999'}]}

        with patch.object(mp_utils, 'site') as site, patch.object(mp_utils, '_upsert_async', side_effect=[
            [_UNIQUE_VIOLATION],
            [{'entity': 'PriceManagerProduct', 'id': 'pmp-taken', 'stored': True, 'status': 'Updated'}],
        ]) as upsert:
            site.get.side_effect = site_get
            with self.assertLogs(mp_utils.logger, level='WARNING'):
                self.assertEqual(push_pim_links([product.pk], delay=0), 1)

        takeover = upsert.call_args_list[1].args[1][0]['payload']
        self.assertEqual(takeover['id'], 'pmp-taken')
        self.assertEqual(takeover['platformID'], str(product.pk))
        product.refresh_from_db()
        previous_owner.refresh_from_db()
        self.assertEqual(product.pim_id, 'pmp-taken')
        self.assertIsNone(previous_owner.pim_id)

    def test_rejection_nothing_can_place_is_recorded_and_raises(self):
        rejected = self.waiting_product('REJECTED')
        created = self.waiting_product('CREATED')

        def site_get(entity):
            if entity.name == 'Product':
                return _pim_list()
            return {'list': []}  # no PMP holds the number, so nothing to take over

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, '_upsert_async', return_value=[_UNIQUE_VIOLATION, _created('pmp-2')]), \
                self.assertLogs(mp_utils.logger, level='ERROR'):
            site.get.side_effect = site_get
            with self.assertRaises(PimScanError):
                push_pim_links([rejected.pk, created.pk], delay=0)

        rejected.refresh_from_db()
        created.refresh_from_db()
        self.assertIsNone(rejected.pim_id)
        self.assertEqual(created.pim_id, 'pmp-2')
        error = cache.get(mp_utils._PIM_LAST_ERROR_KEY)
        self.assertEqual(error['op'], 'push_pim_links')
        self.assertIn('1 из 2', error['error'])

    def test_product_already_pushed_or_unlinked_is_left_alone(self):
        pushed = PimProduct.objects.create(number='PUSHED', pim_id='pmp-1')
        self.product(sku='PUSHED', product=pushed)
        orphan = PimProduct.objects.create(number='ORPHAN')

        with patch.object(mp_utils, 'site') as site, patch.object(mp_utils, '_upsert_async') as upsert:
            self.assertEqual(push_pim_links([pushed.pk, orphan.pk], delay=0), 0)

        site.get.assert_not_called()
        upsert.assert_not_called()


@override_settings(CACHES=LOCMEM_CACHE)
class GetPimDataTests(_PimSearchTestCase):
    """Reads go PriceManagerProduct -> productId -> Product."""

    def _site(self, links=None, products=None):
        links = links or {}
        products = products or {}

        def get(entity):
            table = links if entity.name == 'PriceManagerProduct' else products
            answer = table[entity.id]
            if isinstance(answer, Exception):
                raise answer
            return answer
        return get

    @staticmethod
    def _not_found():
        request = httpx.Request('GET', 'https://pim.invalid/api/x')
        return httpx.HTTPStatusError('404', request=request, response=httpx.Response(404, request=request))

    def test_two_hops_return_the_pim_product(self):
        with patch.object(mp_utils, 'site') as site:
            site.get.side_effect = self._site(
                links={'pmp-1': {'id': 'pmp-1', 'productId': 'prod-1'}},
                products={'prod-1': {'id': 'prod-1', 'name': 'Дрель'}},
            )
            self.assertEqual(get_pim_data('pmp-1'), {'id': 'prod-1', 'name': 'Дрель'})

    def test_link_without_product_id_has_no_data(self):
        with patch.object(mp_utils, 'site') as site:
            site.get.side_effect = self._site(links={'pmp-1': {'id': 'pmp-1', 'productId': None}})
            self.assertIsNone(get_pim_data('pmp-1'))

        self.assertEqual([c.args[0].name for c in site.get.call_args_list], ['PriceManagerProduct'])

    def test_links_sharing_a_pim_product_share_one_product_fetch(self):
        with patch.object(mp_utils, 'site') as site:
            site.get.side_effect = self._site(
                links={
                    'pmp-1': {'id': 'pmp-1', 'productId': 'prod-1'},
                    'pmp-2': {'id': 'pmp-2', 'productId': 'prod-1'},
                },
                products={'prod-1': {'id': 'prod-1'}},
            )
            get_pim_data('pmp-1')
            get_pim_data('pmp-2')

        fetched = [(c.args[0].name, c.args[0].id) for c in site.get.call_args_list]
        self.assertEqual(fetched.count(('Product', 'prod-1')), 1)

    def test_repeated_404_on_the_link_clears_pim_id_but_keeps_the_main_product_link(self):
        main_product = self.product(sku='N-1', pim_id='pmp-dead')

        with patch.object(mp_utils, 'site') as site:
            site.get.side_effect = self._site(links={'pmp-dead': self._not_found()})
            for _ in range(mp_utils._PIM_404_THRESHOLD):
                self.assertIsNone(get_pim_data('pmp-dead'))

        main_product.refresh_from_db()
        self.assertIsNotNone(main_product.product_id)
        self.assertIsNone(main_product.product.pim_id)

    def test_404_on_the_pim_product_changes_nothing_locally(self):
        main_product = self.product(sku='N-1', pim_id='pmp-1')

        with patch.object(mp_utils, 'site') as site:
            site.get.side_effect = self._site(
                links={'pmp-1': {'id': 'pmp-1', 'productId': 'prod-gone'}},
                products={'prod-gone': self._not_found()},
            )
            for _ in range(mp_utils._PIM_404_THRESHOLD):
                self.assertIsNone(get_pim_data('pmp-1', refresh=True))

        main_product.refresh_from_db()
        self.assertEqual(main_product.product.pim_id, 'pmp-1')


class LinkToLocalProductTests(_PimSearchTestCase):
    """The render path links to an existing Product only — it never creates one or asks PIM."""

    def test_links_to_the_product_numbered_like_the_sku(self):
        existing = PimProduct.objects.create(number='SKU-1')
        main_product = self.product(sku='SKU-1')

        with patch.object(mp_utils, 'site') as site:
            self.assertTrue(_link_to_local_product(main_product))

        site.get.assert_not_called()
        main_product.refresh_from_db()
        self.assertEqual(main_product.product_id, existing.pk)

    def test_no_matching_product_creates_nothing(self):
        main_product = self.product(sku='SKU-NEW')

        with patch.object(mp_utils, 'site') as site:
            self.assertFalse(_link_to_local_product(main_product))

        site.get.assert_not_called()
        self.assertEqual(PimProduct.objects.count(), 0)


class LinkToLocalProductsTests(_PimSearchTestCase):
    """Batched link for copy-to-main: existing Products only, one lookup for the lot."""

    def test_links_every_row_whose_sku_names_an_existing_product(self):
        first = PimProduct.objects.create(number='SKU-1')
        second = PimProduct.objects.create(number='SKU-2')
        rows = [self.product(sku='SKU-1'), self.product(sku='SKU-2'), self.product(sku='SKU-NONE')]

        with patch.object(mp_utils, 'site') as site:
            linked = link_to_local_products([row.pk for row in rows])

        self.assertEqual(linked, 2)
        site.get.assert_not_called()
        self.assertEqual(PimProduct.objects.count(), 2)
        self.assertEqual(
            {row.sku: row.product_id for row in MainProduct.objects.filter(pk__in=[r.pk for r in rows])},
            {'SKU-1': first.pk, 'SKU-2': second.pk, 'SKU-NONE': None},
        )

    def test_an_existing_link_is_never_overwritten(self):
        mine = PimProduct.objects.create(number='OTHER')
        PimProduct.objects.create(number='SKU-1')
        row = self.product(sku='SKU-1', product=mine)

        self.assertEqual(link_to_local_products([row.pk]), 0)
        row.refresh_from_db()
        self.assertEqual(row.product_id, mine.pk)

    def test_query_count_does_not_grow_with_the_rows(self):
        for n in range(5):
            PimProduct.objects.create(number=f'SKU-{n}')
        rows = [self.product(sku=f'SKU-{n}') for n in range(5)]

        with self.assertNumQueries(3):  # rows, products, one bulk update
            link_to_local_products([row.pk for row in rows])


class CreateLinksToProductTests(_PimSearchTestCase):
    """«Добавить товар»: the new row is linked explicitly, not as a vector side effect."""

    def test_created_row_is_linked_to_the_product_with_its_sku(self):
        from django.contrib.auth.models import User
        from django.urls import reverse

        product = PimProduct.objects.create(number='NEW-1')
        self.client.force_login(User.objects.create_user(username='creator', password='pw'))

        with patch.object(mp_utils, 'site'):
            response = self.client.post(reverse('mainproduct-create'), {
                'mpcreate-supplier': self.supplier.pk, 'mpcreate-article': 'A-NEW',
                'mpcreate-name': 'Новый', 'mpcreate-sku': 'NEW-1', 'mpcreate-stock': 3,
            }, HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(MainProduct.objects.get(article='A-NEW').product_id, product.pk)


from django.contrib.auth.models import User

from core.models import PersistentNotification
from .utils import _record_pim_error, maybe_notify_pim_error


@override_settings(CACHES=LOCMEM_CACHE, DEBUG=False)
class PimErrorNotificationTests(TestCase):
    """maybe_notify_pim_error used to return early unless settings.DEBUG.

    That inverted the intent: DEBUG defaults to false (settings/base.py), so
    production — where a PIM outage actually costs something — was the one
    environment that got no signal. DEBUG=False here is the point of the class,
    not incidental. The throttle lives in the cache, hence locmem.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='pim-watcher', password='pw')

    def _notification_count(self):
        return PersistentNotification.objects.filter(user=self.user).count()

    def test_notifies_even_though_debug_is_false(self):
        _record_pim_error('get_pim_data', RuntimeError('PIM down'), 12)

        maybe_notify_pim_error(self.user)

        self.assertEqual(self._notification_count(), 1)

    def test_repeat_calls_are_throttled_per_user(self):
        _record_pim_error('get_pim_data', RuntimeError('PIM down'), 12)

        maybe_notify_pim_error(self.user)
        maybe_notify_pim_error(self.user)

        self.assertEqual(self._notification_count(), 1)

    def test_no_recorded_error_means_no_notification(self):
        maybe_notify_pim_error(self.user)

        self.assertEqual(self._notification_count(), 0)


class SyncButtonTests(TestCase):
    """«Обновить» есть и на старой главной, и на /products/."""

    def test_sync_refreshes_the_page_it_was_pressed_on(self):
        from unittest import mock

        from django.contrib.auth.models import User
        from django.urls import reverse

        user = User.objects.create_user(username='sync-tester', password='pw')
        self.client.force_login(user)

        with mock.patch('main_product_manager.views.sync_main_products_task') as task:
            response = self.client.get(reverse('mainproducts-sync'), HTTP_HX_REQUEST='true',
                                       HTTP_REFERER='/products/')

        task.assert_called_once_with(user.pk)
        # HX-Refresh, а не HX-Redirect на 'mainproducts': иначе кнопка на
        # товарной странице уводила бы на старую главную.
        self.assertEqual(response.headers.get('HX-Refresh'), 'true')
        self.assertNotIn('HX-Redirect', response.headers)


class MainProductExportTests(_PimSearchTestCase):
    """Выгрузка главного прайса: колонки прежние, значения — из PIM (Product)."""

    def test_brand_group_and_description_come_from_the_product(self):
        from product.models import Brand, Category

        from .resources import MainProductResource

        root = Category.objects.create(name='Инструмент')
        leaf = Category.objects.create(name='Дрели', parent=root)
        product = PimProduct.objects.create(
            number='EXP-1', brand=Brand.objects.create(pim_id='b-1', name='Bosch'),
            raw_data={'description': '<p>Мощная</p>'},
        )
        product.categories.add(leaf)
        self.product(sku='EXP-1', product=product)
        without_product = self.product(sku='EXP-2')  # без товара — пустые колонки, а не ошибка
        SupplierProduct.objects.create(main_product=without_product, supplier=self.supplier,
                                       article=without_product.article, name=without_product.name,
                                       description='Из прайса')

        rows = {row['sku']: row for row in MainProductResource().export(MainProduct.objects.all()).dict}

        self.assertEqual(rows['EXP-1']['Производитель'], 'Bosch')
        self.assertEqual(rows['EXP-1']['Название_группы'], 'Инструмент > Дрели')
        self.assertEqual(rows['EXP-1']['HTML_описание'], '<p>Мощная</p>')
        self.assertEqual((rows['EXP-2']['Производитель'], rows['EXP-2']['Название_группы']), ('', ''))
        # Описание — прежде всего из строки прайса: именно его хранил удалённый
        # MainProduct.description. Без этого у товаров без контента PIM (их
        # большинство) колонка опустела бы.
        self.assertEqual(rows['EXP-2']['HTML_описание'], 'Из прайса')

    def test_supplier_row_description_wins_over_pim(self):
        from .resources import MainProductResource

        product = PimProduct.objects.create(number='EXP-3', raw_data={'description': 'Из PIM'})
        mp = self.product(sku='EXP-3', product=product)
        SupplierProduct.objects.create(main_product=mp, supplier=self.supplier, article=mp.article,
                                       name=mp.name, description='Из прайса')

        row = MainProductResource().export(MainProduct.objects.all()).dict[0]

        self.assertEqual(row['HTML_описание'], 'Из прайса')

    def test_the_dropped_columns_are_no_longer_importable(self):
        from .resources import MainProductResource

        imported = [field.column_name for field in MainProductResource().get_import_fields()]

        self.assertNotIn('Производитель', imported)
        self.assertNotIn('Название_группы', imported)
