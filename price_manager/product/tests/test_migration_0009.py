import contextlib
import importlib
import io

from django.apps import apps
from django.db import IntegrityError, connection
from django.test import TestCase

from main_product_manager.models import MainProduct
from product.models import Brand, Product
from supplier_manager.models import Currency, Supplier

migration = importlib.import_module('product.migrations.0009_product_number_case_insensitive')


class ProductNumberBrandConstraintTests(TestCase):
    """The standing constraint: product.0009 made number unique case-insensitively,
    product.0021 narrowed that to the pair (Lower(number), brand), brand set.

    Brandless products sharing a number are different products until they get
    a brand, so only a branded pair is guarded.
    """

    def test_constraint_rejects_a_case_variant_of_a_branded_pair(self):
        brand = Brand.objects.create(pim_id='brand-1', name='Bosch')
        Product.objects.create(number='abc123', brand=brand)

        with self.assertRaises(IntegrityError):
            Product.objects.create(number='ABC123', brand=brand)

    def test_same_number_under_another_brand_or_none_is_allowed(self):
        bosch = Brand.objects.create(pim_id='brand-1', name='Bosch')
        makita = Brand.objects.create(pim_id='brand-2', name='Makita')
        Product.objects.create(number='abc123', brand=bosch)

        Product.objects.create(number='ABC123', brand=makita)
        Product.objects.create(number='abc123')
        Product.objects.create(number='abc123')

        self.assertEqual(Product.objects.filter(number__iexact='abc123').count(), 4)


class MergeCaseDuplicateNumbersTests(TestCase):
    """The data step of product.0009, run against the live registry.

    CI migrates an empty database, where the step has nothing to touch; this
    is the only place its filters meet rows. Brandless case-variant duplicates
    can be created directly since product.0021 replaced the unique
    Lower(number) with the (Lower(number), brand) pair, so the fixtures need
    no index dropped any more.
    """

    def setUp(self):
        currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Migration supplier',
            currency=currency,
            delivery_days_available=1,
            delivery_days_navailable=2,
        )

    def _run(self):
        # A real schema editor, not None: the step flushes deferred FK
        # triggers through it (SET CONSTRAINTS), as RunPython would.
        with contextlib.redirect_stdout(io.StringIO()), connection.schema_editor(atomic=False) as schema_editor:
            migration.merge_case_duplicate_numbers(apps, schema_editor)

    def test_merges_into_existing_lowercase_and_relinks_main_product(self):
        lower = Product.objects.create(number='abc123', pim_id='pmp-1')
        upper = Product.objects.create(number='ABC123')
        mp = MainProduct.objects.create(supplier=self.supplier, article='A', name='A', product=upper)

        self._run()

        self.assertFalse(Product.objects.filter(pk=upper.pk).exists())
        mp.refresh_from_db()
        self.assertEqual(mp.product_id, lower.pk)
        self.assertEqual(Product.objects.get(pk=lower.pk).number, 'abc123')

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
