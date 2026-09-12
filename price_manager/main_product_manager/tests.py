from django.test import TestCase

from supplier_manager.models import Manufacturer, ManufacturerDict
from .resources import ManufacturerWidget


class ManufacturerWidgetTests(TestCase):
    def setUp(self):
        self.widget = ManufacturerWidget(Manufacturer, "name")

    def test_clean_uses_existing_manufacturer_case_insensitive(self):
        manufacturer = Manufacturer.objects.create(name="Bosch")

        result = self.widget.clean("bosch")

        self.assertEqual(result, manufacturer)
        self.assertEqual(Manufacturer.objects.count(), 1)

    def test_clean_uses_dictionary_mapping(self):
        manufacturer = Manufacturer.objects.create(name="DeWALT")
        ManufacturerDict.objects.create(name="Dewalt tools", manufacturer=manufacturer)

        result = self.widget.clean("dewalt tools")

        self.assertEqual(result, manufacturer)
        self.assertEqual(Manufacturer.objects.count(), 1)

    def test_clean_autobinds_close_name_to_existing_manufacturer(self):
        manufacturer = Manufacturer.objects.create(name="Makita")

        result = self.widget.clean("Makitta")

        self.assertEqual(result, manufacturer)
        self.assertTrue(
            ManufacturerDict.objects.filter(name="Makitta", manufacturer=manufacturer).exists()
        )
        self.assertEqual(Manufacturer.objects.count(), 1)

    def test_clean_creates_new_manufacturer_when_no_match(self):
        result = self.widget.clean("Completely New Brand")

        self.assertEqual(result.name, "Completely New Brand")
        self.assertEqual(Manufacturer.objects.count(), 1)

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

from django.core.cache import cache
from django.db import transaction
from django.test import override_settings

from core.task_runner import dispatch_after_commit
from . import tasks as mp_tasks
from . import utils as mp_utils
from .utils import _queue_pim_population

# execute_locked_task's lock and _queue_pim_population's dedup flag both live in
# the cache; keep them off the shared Redis the worker container points at.
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
                supplier=self.supplier, article=f'RX-{i}', name=f'Reindex {i}'
            )
            for i in range(3)
        ]

    def test_batches_dispatch_only_once_the_transaction_commits(self):
        with patch.object(mp_tasks.reindex_pim_ids_batch_task, 'delay') as delay:
            with self.captureOnCommitCallbacks(execute=True):
                payload = mp_tasks.reindex_pim_ids_task(delay=0, batch_size=2)
                delay.assert_not_called()

            pks = [p.pk for p in self.products]
            self.assertEqual(
                [call.kwargs['pks'] for call in delay.call_args_list],
                [pks[:2], pks[2:]],
            )

        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['updated_count'], 2)


@override_settings(CACHES=LOCMEM_CACHE)
class QueuePimPopulationDispatchTests(TestCase):
    """_queue_pim_population is reached from inside execute_locked_task's
    transaction via _build_searchvector -> _resolve_pim_id, which writes the
    pim_id sync_pim_relations then looks products up by."""

    def setUp(self):
        cache.clear()

    def test_population_task_is_held_until_the_pim_id_write_commits(self):
        with patch.object(mp_tasks.populate_pim_relations_task, 'delay') as delay:
            with self.captureOnCommitCallbacks(execute=True):
                _queue_pim_population('pim-1')
                delay.assert_not_called()

            delay.assert_called_once_with('pim-1')

    def test_dedup_flag_still_collapses_a_burst_of_cache_misses(self):
        with patch.object(mp_tasks.populate_pim_relations_task, 'delay') as delay:
            with self.captureOnCommitCallbacks(execute=True):
                _queue_pim_population('pim-2')
                _queue_pim_population('pim-2')

            delay.assert_called_once_with('pim-2')


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
    PimSearchError,
    _PIM_NO_MATCH_TTL,
    _PIM_SEARCH_ERROR_TTL,
    _SEARCH_ABSENT,
    _SEARCH_AMBIGUOUS,
    _SEARCH_ERROR,
    _SEARCH_FOUND,
    _SEARCH_NO_SKU,
    _search_pim_id_result,
    create_pim_links,
    reindex_pim_ids_batch,
)


def _pim_list(*ids):
    return {'list': [{'id': pim_id} for pim_id in ids]}


class _PimSearchTestCase(TestCase):
    """Shared fixture for the pim_id search: a supplier plus MainProduct factory.

    _search_pim_id_result caches under pim_no_match:{pk}, so every test here
    needs the locmem cache rather than the worker container's shared Redis.
    """

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
        # pim_id= — удобство фабрики: связь теперь FK на product.Product.
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
class SearchPimIdOutcomeTests(_PimSearchTestCase):
    """An empty result from _search_pim_id_result has to say *why* it is empty.

    Only _SEARCH_ABSENT means PIM answered; everything else is "unknown" and
    must not reach push_missing_pim_products.
    """

    def test_single_match_returns_the_id(self):
        product = self.product()

        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list('pim-42')
            pim_id, outcome = _search_pim_id_result(product)

        self.assertEqual((pim_id, outcome), ('pim-42', _SEARCH_FOUND))
        self.assertIsNone(cache.get(f'pim_no_match:{product.pk}'))

    def test_empty_result_is_a_confirmed_absence(self):
        product = self.product()

        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list()
            pim_id, outcome = _search_pim_id_result(product)

        self.assertIsNone(pim_id)
        self.assertEqual(outcome, _SEARCH_ABSENT)
        self.assertEqual(cache.get(f'pim_no_match:{product.pk}'), _SEARCH_ABSENT)

    def test_pim_error_is_not_recorded_as_a_confirmed_absence(self):
        product = self.product()

        with patch.object(mp_utils, 'site') as site:
            site.get.side_effect = RuntimeError('PIM down')
            pim_id, outcome = _search_pim_id_result(product)

        self.assertIsNone(pim_id)
        self.assertEqual(outcome, _SEARCH_ERROR)
        self.assertEqual(cache.get(f'pim_no_match:{product.pk}'), _SEARCH_ERROR)

    def test_error_backoff_is_far_shorter_than_the_no_match_ttl(self):
        # The whole point of defect 1: a PIM outage must cost minutes of
        # suppressed retries, not the 4 hours a genuine absence gets.
        product = self.product()
        self.assertLess(_PIM_SEARCH_ERROR_TTL, _PIM_NO_MATCH_TTL)

        with patch.object(mp_utils, 'site') as site, patch.object(mp_utils, 'cache') as cache_mock:
            cache_mock.get.return_value = None
            site.get.side_effect = RuntimeError('PIM down')
            _search_pim_id_result(product)

        # _record_pim_error writes _PIM_LAST_ERROR_KEY through the same cache,
        # so assert on this call rather than on the only call.
        cache_mock.set.assert_any_call(
            f'pim_no_match:{product.pk}', _SEARCH_ERROR, _PIM_SEARCH_ERROR_TTL
        )

        with patch.object(mp_utils, 'site') as site, patch.object(mp_utils, 'cache') as cache_mock:
            cache_mock.get.return_value = None
            site.get.return_value = _pim_list()
            _search_pim_id_result(product)

        cache_mock.set.assert_called_once_with(
            f'pim_no_match:{product.pk}', _SEARCH_ABSENT, _PIM_NO_MATCH_TTL
        )

    def test_cached_error_does_not_become_an_absence_on_the_next_call(self):
        product = self.product()
        cache.set(f'pim_no_match:{product.pk}', _SEARCH_ERROR, _PIM_SEARCH_ERROR_TTL)

        with patch.object(mp_utils, 'site') as site:
            pim_id, outcome = _search_pim_id_result(product)

        site.get.assert_not_called()
        self.assertIsNone(pim_id)
        self.assertEqual(outcome, _SEARCH_ERROR)

    def test_cached_absence_is_still_an_absence_on_the_next_call(self):
        # The complement of the test above: caching the outcome must not cost
        # the scans their one legitimate reason to push a product to PIM.
        product = self.product()
        cache.set(f'pim_no_match:{product.pk}', _SEARCH_ABSENT, _PIM_NO_MATCH_TTL)

        with patch.object(mp_utils, 'site') as site:
            pim_id, outcome = _search_pim_id_result(product)

        site.get.assert_not_called()
        self.assertIsNone(pim_id)
        self.assertEqual(outcome, _SEARCH_ABSENT)

    def test_a_bare_true_from_an_older_revision_triggers_a_fresh_search(self):
        product = self.product()
        cache.set(f'pim_no_match:{product.pk}', True, _PIM_NO_MATCH_TTL)

        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list('pim-7')
            pim_id, outcome = _search_pim_id_result(product)

        self.assertEqual((pim_id, outcome), ('pim-7', _SEARCH_FOUND))

    def test_ambiguous_match_links_nothing(self):
        # Kept under `equals`, though it may now be unreachable in practice: a
        # sample of 2400 consecutive PIM numbers held no duplicates. Nothing
        # checked *guarantees* `number` is unique, though, and the guard costs
        # one len() — returning the first of several would link an arbitrary one.
        product = self.product(sku='AB-1')

        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list('pim-1', 'pim-2')
            pim_id, outcome = _search_pim_id_result(product)

        self.assertIsNone(pim_id)
        self.assertEqual(outcome, _SEARCH_AMBIGUOUS)
        self.assertEqual(cache.get(f'pim_no_match:{product.pk}'), _SEARCH_AMBIGUOUS)

    def test_search_uses_equals_so_sku_wildcards_stay_literal(self):
        """AtroPIM feeds a `like` value straight into SQL LIKE.

        Measured against the live API: `like '2001_-04_z01'` returns the
        product numbered `20015-04_z01` (so `_` is a single-char wildcard) and
        `like '%'` returns the whole catalog. PIM numbers routinely carry `_`
        and sku is supplier-supplied, so under `like` a sku can match a
        *different* product. When exactly one such match comes back the
        ambiguity guard never fires and _resolve_pim_id writes the wrong
        pim_id — silently. `equals` keeps both characters literal.
        """
        product = self.product(sku='2001_-04_z01')

        with patch.object(mp_utils, 'site') as site:
            site.get.return_value = _pim_list('pim-1')
            _search_pim_id_result(product)

            entity_list = site.get.call_args.args[0]

        self.assertEqual(entity_list.name, 'Product')
        self.assertEqual(
            [(w.attribute, w.type, w.value) for w in entity_list.where],
            [('number', 'equals', '2001_-04_z01')],
        )

    def test_product_without_sku_is_never_searched(self):
        # Where.get() omits the value key when it is None, so the request would
        # go out as an unconstrained match on number and return everything.
        product = self.product(sku=None, article='NO-SKU')

        with patch.object(mp_utils, 'site') as site:
            pim_id, outcome = _search_pim_id_result(product)

        site.get.assert_not_called()
        self.assertIsNone(pim_id)
        self.assertEqual(outcome, _SEARCH_NO_SKU)


@override_settings(CACHES=LOCMEM_CACHE)
class PimScanPushGuardTests(_PimSearchTestCase):
    """The scans may only push products PIM actually confirmed it doesn't have.

    push_missing_pim_products creates a new PriceManagerProduct, so pushing on
    an unanswered search duplicates a product that may already be in PIM.
    """

    def _site_by_sku(self, responses):
        """site.get double: maps the `number` filter value to a response/exception."""
        def get(entity):
            answer = responses[entity.where[0].value]
            if isinstance(answer, Exception):
                raise answer
            return answer
        return get

    def test_create_pim_links_pushes_the_absence_but_not_the_failed_search(self):
        absent = self.product(sku='ABSENT')
        errored = self.product(sku='ERRORED')

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, 'push_missing_pim_products', return_value=0) as push:
            site.get.side_effect = self._site_by_sku({
                'ABSENT': _pim_list(),
                'ERRORED': RuntimeError('PIM down'),
            })
            with self.assertRaises(PimSearchError):
                create_pim_links(delay=0)

        pushed = [p.pk for call in push.call_args_list for p in call.args[0]]
        self.assertEqual(pushed, [absent.pk])
        self.assertNotIn(errored.pk, pushed)

    def test_create_pim_links_keeps_the_links_it_resolved_before_raising(self):
        linked = self.product(sku='LINKED')
        errored = self.product(sku='ERRORED')

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, 'push_missing_pim_products', return_value=0):
            site.get.side_effect = self._site_by_sku({
                'LINKED': _pim_list('pim-99'),
                'ERRORED': RuntimeError('PIM down'),
            })
            with self.assertRaises(PimSearchError):
                create_pim_links(delay=0)

        linked.refresh_from_db()
        errored.refresh_from_db()
        self.assertEqual(linked.product.pim_id, 'pim-99')
        self.assertIsNone(errored.product)

    def test_create_pim_links_succeeds_when_every_search_was_answered(self):
        self.product(sku='LINKED')
        self.product(sku='ABSENT')

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, 'push_missing_pim_products', return_value=1) as push:
            site.get.side_effect = self._site_by_sku({
                'LINKED': _pim_list('pim-1'),
                'ABSENT': _pim_list(),
            })
            linked, created = create_pim_links(delay=0)

        self.assertEqual((linked, created), (1, 1))
        self.assertEqual(len(push.call_args_list[-1].args[0]), 1)

    def test_create_pim_links_skips_products_with_no_sku_entirely(self):
        # They cannot be searched and must not be pushed (the PIM record would
        # carry number=''), so they must not consume a slot in the 1000-row
        # window either.
        searchable = self.product(sku='SEARCHABLE')
        self.product(sku=None, article='NO-SKU')

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, 'push_missing_pim_products', return_value=0) as push:
            site.get.side_effect = self._site_by_sku({'SEARCHABLE': _pim_list('pim-5')})
            linked, created = create_pim_links(delay=0)

        searchable.refresh_from_db()
        self.assertEqual((linked, created), (1, 0))
        self.assertEqual(searchable.product.pim_id, 'pim-5')
        self.assertEqual(push.call_args.args[0], [])

    def test_reindex_batch_raises_and_leaves_the_errored_product_alone(self):
        linked = self.product(sku='LINKED', pim_id='pim-old')
        errored = self.product(sku='ERRORED', pim_id='pim-keep')
        unlinked = self.product(sku='ERRORED-NEW')

        with patch.object(mp_utils, 'site') as site, \
                patch.object(mp_utils, 'push_missing_pim_products', return_value=0) as push:
            site.get.side_effect = self._site_by_sku({
                'LINKED': _pim_list('pim-new'),
                'ERRORED': RuntimeError('PIM down'),
                'ERRORED-NEW': RuntimeError('PIM down'),
            })
            with self.assertRaises(PimSearchError):
                reindex_pim_ids_batch([linked.pk, errored.pk, unlinked.pk], delay=0)

        linked.refresh_from_db()
        errored.refresh_from_db()
        self.assertEqual(linked.product.pim_id, 'pim-new')
        self.assertEqual(errored.product.pim_id, 'pim-keep')
        self.assertEqual(push.call_args.args[0], [])


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
