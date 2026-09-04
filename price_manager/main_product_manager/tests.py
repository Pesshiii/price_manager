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
