import contextlib
import importlib
import io

from django.apps import apps
from django.db import IntegrityError, connection
from django.test import TestCase

from main_product_manager.models import MainProduct
from product.models import Brand, Product
from supplier.models import Supplier as FeedSupplier
from supplier_feed.models import SupplierLink
from supplier_manager.models import Currency, Supplier

migration = importlib.import_module('product.migrations.0009_product_number_case_insensitive')


class ProductNumberCaseInsensitiveConstraintTests(TestCase):
    """The schema-level guarantee product.0009 exists to add: not just a
    one-time cleanup, but a standing constraint against new collisions."""

    def test_constraint_rejects_case_variant_numbers(self):
        Product.objects.create(number='abc123')

        with self.assertRaises(IntegrityError):
            Product.objects.create(number='ABC123')


class MergeCaseDuplicateNumbersTests(TestCase):
    """The data step of product.0009, run against the live registry.

    CI migrates an empty database, where the step has nothing to touch; this
    is the only place its filters meet rows. Case-variant duplicates can no
    longer be created directly once product_product_number_lower_uniq exists.
    It's an expression index, not a pg_constraint row (Postgres has no
    table-level CONSTRAINT for an indexed expression — see the migration's
    sqlmigrate output: CREATE UNIQUE INDEX ... ((LOWER("number")))), so it
    comes off with DROP INDEX rather than ALTER TABLE ... DROP CONSTRAINT.
    Postgres DDL is transactional, so each test drops it to set up its
    fixture and the per-test rollback restores it afterwards without
    touching other tests or the constraint test above.
    """

    def setUp(self):
        currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Migration supplier',
            currency=currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )
        with connection.cursor() as cursor:
            cursor.execute('DROP INDEX product_product_number_lower_uniq')

    def _run(self):
        with contextlib.redirect_stdout(io.StringIO()):
            migration.merge_case_duplicate_numbers(apps, None)

    def test_merges_into_existing_lowercase_and_relinks_main_product(self):
        lower = Product.objects.create(number='abc123', pim_id='pmp-1')
        upper = Product.objects.create(number='ABC123')
        mp = MainProduct.objects.create(supplier=self.supplier, article='A', name='A', product=upper)

        self._run()

        self.assertFalse(Product.objects.filter(pk=upper.pk).exists())
        mp.refresh_from_db()
        self.assertEqual(mp.product_id, lower.pk)
        self.assertEqual(Product.objects.get(pk=lower.pk).number, 'abc123')

    def test_relinks_supplier_link_before_deleting_cascade_fk(self):
        # SupplierLink.product is on_delete=CASCADE: deleting the losing row
        # without repointing this first would silently take the link with it.
        lower = Product.objects.create(number='abc123')
        upper = Product.objects.create(number='ABC123')
        link = SupplierLink.objects.create(
            supplier=FeedSupplier.objects.create(name='Feed supplier'),
            supplier_sku='FEED-1',
            product=upper,
        )

        self._run()

        link.refresh_from_db()
        self.assertEqual(link.product_id, lower.pk)

    def test_no_lowercase_variant_picks_lowest_pk_and_swaps_it(self):
        first = Product.objects.create(number='ABC123')
        second = Product.objects.create(number='AbC123')

        self._run()

        self.assertFalse(Product.objects.filter(pk=second.pk).exists())
        self.assertEqual(Product.objects.get(pk=first.pk).number, 'abc123')

    def test_fills_gaps_from_the_deleted_row(self):
        brand = Brand.objects.create(pim_id='brand-1', name='Bosch')
        lower = Product.objects.create(number='abc123', name=None)
        Product.objects.create(number='ABC123', name='Товар', pim_id='pmp-1', brand=brand)

        self._run()

        winner = Product.objects.get(pk=lower.pk)
        self.assertEqual(winner.name, 'Товар')
        self.assertEqual(winner.pim_id, 'pmp-1')
        self.assertEqual(winner.brand_id, brand.pk)

    def test_conflicting_pim_id_keeps_winners_and_discards_losers(self):
        # On real data every collision group holds two different pim_id
        # values (both variants were independently pushed to PIM already) --
        # raising here would make the migration undeployable, so the winner
        # keeps its own link and the loser's is discarded with it.
        lower = Product.objects.create(number='abc123', pim_id='pmp-1')
        Product.objects.create(number='ABC123', pim_id='pmp-2')

        self._run()

        self.assertEqual(Product.objects.get().pk, lower.pk)
        self.assertEqual(Product.objects.get().pim_id, 'pmp-1')

    def test_non_colliding_numbers_are_left_untouched(self):
        Product.objects.create(number='XYZ999')

        self._run()

        self.assertEqual(Product.objects.get(number='XYZ999').number, 'XYZ999')
