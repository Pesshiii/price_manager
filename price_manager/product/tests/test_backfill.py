from unittest.mock import patch

from django.test import TestCase

from product.models import Product
from product.services.pim_sync import (
    iter_unsynced_product_pk_batches,
    sync_products,
    unsynced_products,
)

SYNC_ONE_PATCH = 'product.services.pim_sync.sync_product_from_pim'


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
