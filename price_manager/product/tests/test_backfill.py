from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from pim_api import ListResult

from product import tasks
from product.models import Product
from product.services.pim_sync import (
    iter_unsynced_product_pk_batches,
    stale_product_pks,
    sync_products,
    unsynced_products,
)

SYNC_ONE_PATCH = 'product.services.pim_sync.sync_product_from_pim'
FETCH_LIST_PATCH = 'product.services.pim_sync.fetch_list'
LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


class UnsyncedProductsTests(TestCase):
    """Кого вообще берём в бэкфилл."""

    def test_skips_products_without_pim_id(self):
        """Без pim_id синхронизировать нечем — это работа reindex_pim_ids.

        pim_id и есть тот PriceManagerProduct, через который мы ходим за
        товаром; порядок шагов конвейера держится на этом.
        """
        Product.objects.create(pim_id=None, number='N1')

        self.assertEqual(unsynced_products().count(), 0)

    def test_picks_products_with_pim_id_and_empty_raw_data(self):
        product = Product.objects.create(pim_id='pmp-1', number='N1', raw_data={})

        self.assertEqual(list(unsynced_products()), [product])

    def test_skips_already_synced_products(self):
        Product.objects.create(pim_id='pmp-1', number='N1', raw_data={'name': 'Товар'})

        self.assertEqual(unsynced_products().count(), 0)

    def test_refresh_takes_everything_with_a_pim_id(self):
        Product.objects.create(pim_id='pmp-1', number='N1', raw_data={'name': 'Товар'})
        Product.objects.create(pim_id='pmp-2', number='N2', raw_data={})
        Product.objects.create(pim_id=None, number='N3', raw_data={})

        self.assertEqual(unsynced_products(refresh=True).count(), 2)

    def test_batches_do_not_overlap_and_cover_everything(self):
        for i in range(5):
            Product.objects.create(pim_id=f'pmp-{i}', number=f'N{i}', raw_data={})

        batches = list(iter_unsynced_product_pk_batches(batch_size=2))

        self.assertEqual([len(b) for b in batches], [2, 2, 1])
        flat = [pk for batch in batches for pk in batch]
        self.assertEqual(len(flat), len(set(flat)))


class SyncProductsBatchTests(TestCase):
    def setUp(self):
        self.products = [
            Product.objects.create(pim_id=f'pmp-{i}', number=f'N{i}', raw_data={})
            for i in range(3)
        ]
        self.pks = [p.pk for p in self.products]

    def test_syncs_every_product_in_the_batch(self):
        with patch(SYNC_ONE_PATCH) as sync_one:
            synced = sync_products(self.pks, delay=0)

        self.assertEqual(synced, 3)
        self.assertEqual(
            sorted(call.args[0] for call in sync_one.call_args_list),
            ['pmp-0', 'pmp-1', 'pmp-2'],
        )

    def test_one_failure_does_not_abort_the_rest_of_the_batch(self):
        """PIM отвечает по товару за раз — один 404 не повод потерять остальные."""
        def flaky(pim_id):
            if pim_id == 'pmp-1':
                raise RuntimeError('pim down')
            return Product(pim_id=pim_id, raw_data={'id': 'pim'})

        with patch(SYNC_ONE_PATCH, side_effect=flaky) as sync_one:
            synced = sync_products(self.pks, delay=0)

        self.assertEqual(synced, 2)
        self.assertEqual(sync_one.call_count, 3)

    def test_failed_rows_stay_eligible_for_the_next_run(self):
        """Бэкфилл идемпотентен: сбойная строка остаётся с пустым raw_data."""
        with patch(SYNC_ONE_PATCH, side_effect=RuntimeError('pim down')):
            sync_products(self.pks, delay=0)

        self.assertEqual(unsynced_products().count(), 3)

    def test_products_without_pim_id_are_never_called(self):
        orphan = Product.objects.create(pim_id=None, number='N-orphan')

        with patch(SYNC_ONE_PATCH) as sync_one:
            sync_products([orphan.pk], delay=0)

        sync_one.assert_not_called()

    def test_a_pmp_without_a_pim_product_is_not_counted_as_synced(self):
        """PMP без productId оставляет raw_data пустым — это не успех.

        Иначе история задач показывает «синхронизировано» по партии, в которой
        контент не получил никто, и застывшее зеркало ничем себя не выдаёт.
        """
        def link_only(pim_id):
            return Product(pim_id=pim_id, raw_data={} if pim_id == 'pmp-1' else {'id': 'pim'})

        with patch(SYNC_ONE_PATCH, side_effect=link_only):
            synced = sync_products(self.pks, delay=0)

        self.assertEqual(synced, 2)


def _listing(pmps, pim_products):
    """fetch_list, отвечающий по имени сущности: PMP-ы и товары PIM."""
    rows = {'PriceManagerProduct': pmps, 'Product': pim_products}

    def fetch(site, query, **kwargs):
        items = rows[query.name]
        return ListResult(total=len(items), items=items, truncated=False)
    return fetch


class StaleProductPksTests(TestCase):
    """Кого ночная сверка отправляет забирать заново."""

    MODIFIED = '2026-09-21 10:14:04'

    def _stale(self, pmps, pim_products):
        with patch(FETCH_LIST_PATCH, side_effect=_listing(pmps, pim_products)):
            return stale_product_pks()

    def test_never_synced_row_whose_pmp_now_has_a_product_is_stale(self):
        """Ради этого случая всё и затеяно: PMP привязали в PIM после бэкфилла."""
        product = Product.objects.create(pim_id='pmp-1', number='N1', raw_data={})

        stale = self._stale([{'id': 'pmp-1', 'productId': 'p-1'}],
                            [{'id': 'p-1', 'modifiedAt': self.MODIFIED}])

        self.assertEqual(stale, [product.pk])

    def test_pmp_without_a_product_is_skipped(self):
        """Забирать нечего — ходить за ним каждую ночь незачем."""
        Product.objects.create(pim_id='pmp-1', number='N1', raw_data={})

        self.assertEqual(self._stale([{'id': 'pmp-1', 'productId': None}], []), [])

    def test_product_changed_in_pim_is_stale(self):
        """Описание, дописанное в PIM, двигает modifiedAt — строку надо забрать."""
        product = Product.objects.create(
            pim_id='pmp-1', number='N1', raw_data={'id': 'p-1', 'modifiedAt': self.MODIFIED})

        stale = self._stale([{'id': 'pmp-1', 'productId': 'p-1'}],
                            [{'id': 'p-1', 'modifiedAt': '2026-10-01 08:00:00'}])

        self.assertEqual(stale, [product.pk])

    def test_unchanged_product_is_left_alone(self):
        Product.objects.create(
            pim_id='pmp-1', number='N1', raw_data={'id': 'p-1', 'modifiedAt': self.MODIFIED})

        stale = self._stale([{'id': 'pmp-1', 'productId': 'p-1'}],
                            [{'id': 'p-1', 'modifiedAt': self.MODIFIED}])

        self.assertEqual(stale, [])

    def test_the_same_moment_in_another_notation_is_unchanged(self):
        """Иначе весь каталог каждую ночь выглядел бы изменённым."""
        Product.objects.create(
            pim_id='pmp-1', number='N1', raw_data={'id': 'p-1', 'modifiedAt': self.MODIFIED})

        stale = self._stale([{'id': 'pmp-1', 'productId': 'p-1'}],
                            [{'id': 'p-1', 'modifiedAt': '2026-09-21T10:14:04'}])

        self.assertEqual(stale, [])

    def test_a_listing_without_modified_at_is_unknown_not_changed(self):
        """Списочный режим PIM молча теряет поля. Пропавший modifiedAt не должен
        каждую ночь отправлять весь каталог на перезагрузку."""
        Product.objects.create(
            pim_id='pmp-1', number='N1', raw_data={'id': 'p-1', 'modifiedAt': self.MODIFIED})

        stale = self._stale([{'id': 'pmp-1', 'productId': 'p-1'}], [{'id': 'p-1'}])

        self.assertEqual(stale, [])

    def test_pmp_relinked_to_another_product_is_stale(self):
        product = Product.objects.create(
            pim_id='pmp-1', number='N1', raw_data={'id': 'p-1', 'modifiedAt': self.MODIFIED})

        stale = self._stale([{'id': 'pmp-1', 'productId': 'p-2'}],
                            [{'id': 'p-2', 'modifiedAt': self.MODIFIED}])

        self.assertEqual(stale, [product.pk])

    def test_rows_without_pim_id_are_never_stale(self):
        """Наборы держат pim_id NULL и пишутся services/sets.py — не трогаем."""
        Product.objects.create(pim_id=None, number='SET-1', raw_data={'id': 'p-1'})

        stale = self._stale([], [{'id': 'p-1', 'modifiedAt': self.MODIFIED}])

        self.assertEqual(stale, [])

    def test_a_truncated_listing_stops_the_check(self):
        """Недочитанный список — не повод решить, что PMP ни к чему не привязан."""
        truncated = ListResult(total=5, items=[{'id': 'pmp-1', 'productId': 'p-1'}], truncated=True)

        with patch(FETCH_LIST_PATCH, return_value=truncated):
            with self.assertRaises(RuntimeError):
                stale_product_pks()


@override_settings(CACHES=LOCMEM_CACHE)
class RefreshProductsFromPimTaskTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_stale_rows_go_out_in_batches(self):
        with patch.object(tasks, 'stale_product_pks', return_value=[1, 2, 3]), \
                patch.object(tasks.sync_products_batch_task, 'delay') as delay:
            with self.captureOnCommitCallbacks(execute=True):
                payload = tasks.refresh_products_from_pim_task(delay=0, batch_size=2)

        self.assertEqual([call.kwargs['pks'] for call in delay.call_args_list], [[1, 2], [3]])
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['updated_count'], 3)
