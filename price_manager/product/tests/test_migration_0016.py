import contextlib
import importlib
import io

from django.apps import apps
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase

from core.models import CartItem
from main_product_manager.models import MainProduct
from product.models import Product
from supplier_manager.models import Currency, Supplier

migration = importlib.import_module('product.migrations.0016_merge_numberless_products')


class NumberlessProductsMixin:
    """Lets a test create Products without a number, as they were before 0017.

    The ALTERs run inside the test's transaction and roll back with it —
    Postgres DDL is transactional — so the schema other tests see is intact.
    """

    def setUp(self):
        super().setUp()
        with connection.cursor() as cursor:
            cursor.execute('ALTER TABLE product_product ALTER COLUMN number DROP NOT NULL')
            cursor.execute('ALTER TABLE product_product DROP CONSTRAINT product_product_number_not_blank')


class MergeNumberlessProductsTests(NumberlessProductsMixin, TestCase):
    """The data step of product.0016, run against the live registry.

    CI migrates an empty database, where the step has nothing to touch; this
    is the only place its rules meet rows.
    """

    def setUp(self):
        super().setUp()
        currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Migration supplier', currency=currency,
            delivery_days_available=1, delivery_days_navailable=2,
        )

    def row(self, product, sku, **kwargs):
        kwargs.setdefault('supplier', self.supplier)
        return MainProduct.objects.create(
            article=kwargs.pop('article', sku), name=kwargs.pop('name', sku), sku=sku,
            product=product, **kwargs)

    def run_step(self):
        with contextlib.redirect_stdout(io.StringIO()):
            migration.merge_numberless_products(apps, None)

    def test_rows_join_their_skus_product_and_the_empty_placeholder_goes(self):
        twin = Product.objects.create(number='SKU-1')
        self.row(twin, 'SKU-1')
        placeholder = Product.objects.create(number=None)
        moved = self.row(placeholder, 'sku-1 ', article='OTHER')

        self.run_step()

        moved.refresh_from_db()
        self.assertEqual(moved.product_id, twin.pk)
        self.assertFalse(Product.objects.filter(pk=placeholder.pk).exists())

    def test_placeholder_takes_a_free_sku_and_keeps_its_pk(self):
        taken = Product.objects.create(number='TAKEN')
        placeholder = Product.objects.create(number='')
        to_taken = self.row(placeholder, 'TAKEN')
        stays = self.row(placeholder, 'FREE')
        follows = self.row(placeholder, 'free', article='OTHER')

        self.run_step()

        placeholder.refresh_from_db()
        self.assertEqual(placeholder.number, 'FREE')
        self.assertEqual(placeholder.name, 'FREE')
        for row, product in ((to_taken, taken), (stays, placeholder), (follows, placeholder)):
            row.refresh_from_db()
            self.assertEqual(row.product_id, product.pk)

    def test_second_free_sku_gets_a_new_product(self):
        placeholder = Product.objects.create(number=None)
        self.row(placeholder, 'FIRST')
        second = self.row(placeholder, 'SECOND', name='Второй')

        self.run_step()

        second.refresh_from_db()
        self.assertEqual(second.product.number, 'SECOND')
        self.assertEqual(second.product.name, 'Второй')
        self.assertNotEqual(second.product_id, placeholder.pk)

    def test_moved_set_row_stops_being_one_where_the_target_has_a_set_row(self):
        twin = Product.objects.create(number='SET-1')
        self.row(twin, 'SET-1', supplier=None, is_set=True)
        placeholder = Product.objects.create(number=None)
        moved = self.row(placeholder, 'SET-1', article='OTHER', supplier=None, is_set=True)

        self.run_step()

        moved.refresh_from_db()
        self.assertEqual(moved.product_id, twin.pk)
        self.assertFalse(moved.is_set)

    def test_unreferenced_orphan_is_deleted(self):
        orphan = Product.objects.create(number=None)

        self.run_step()

        self.assertFalse(Product.objects.filter(pk=orphan.pk).exists())

    def test_row_without_a_usable_sku_stops_the_migration(self):
        placeholder = Product.objects.create(number=None)
        self.row(placeholder, '  ')

        with self.assertRaisesMessage(RuntimeError, 'нет sku'):
            self.run_step()

    def test_referenced_orphan_stops_the_migration(self):
        # CartItem.source_set is SET_NULL: deleting the orphan would silently
        # drop the cart's «из набора» label.
        orphan = Product.objects.create(number=None)
        CartItem.objects.create(user=User.objects.create(username='cart'), source_set=orphan)

        with self.assertRaisesMessage(RuntimeError, 'core.CartItem.source_set'):
            self.run_step()
