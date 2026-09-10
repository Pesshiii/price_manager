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


from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import transaction
from django.test import override_settings

from core.task_runner import dispatch_after_commit
from . import tasks as mp_tasks
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
