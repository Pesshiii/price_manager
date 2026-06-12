from django.db import IntegrityError
from django.test import TestCase, override_settings

from pricing.models import PriceType, ProductPrice, Stock
from .fixtures import make_price_type, make_product, make_supplier


@override_settings(SECURE_SSL_REDIRECT=False)
class PriceTypeStrTests(TestCase):
    def test_str_returns_label(self):
        pt = make_price_type(name='закупочная', label='Закупочная цена')
        self.assertEqual(str(pt), 'Закупочная цена')


@override_settings(SECURE_SSL_REDIRECT=False)
class ProductPriceConstraintTests(TestCase):
    def setUp(self):
        self.product = make_product()
        self.supplier = make_supplier()
        self.price_type = make_price_type()

    def test_unique_constraint(self):
        ProductPrice.objects.create(
            product=self.product,
            supplier=self.supplier,
            price_type=self.price_type,
            value=100,
        )
        with self.assertRaises(IntegrityError):
            ProductPrice.objects.create(
                product=self.product,
                supplier=self.supplier,
                price_type=self.price_type,
                value=200,
            )

    def test_upsert_semantics(self):
        obj, created = ProductPrice.objects.update_or_create(
            product=self.product,
            supplier=self.supplier,
            price_type=self.price_type,
            defaults={'value': 100},
        )
        self.assertTrue(created)
        self.assertEqual(obj.value, 100)

        obj2, created2 = ProductPrice.objects.update_or_create(
            product=self.product,
            supplier=self.supplier,
            price_type=self.price_type,
            defaults={'value': 250},
        )
        self.assertFalse(created2)
        self.assertEqual(obj2.value, 250)
        self.assertEqual(ProductPrice.objects.count(), 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class StockConstraintTests(TestCase):
    def setUp(self):
        self.product = make_product()
        self.supplier = make_supplier()

    def test_unique_constraint(self):
        Stock.objects.create(product=self.product, supplier=self.supplier, quantity=10)
        with self.assertRaises(IntegrityError):
            Stock.objects.create(product=self.product, supplier=self.supplier, quantity=20)

    def test_upsert_semantics(self):
        obj, created = Stock.objects.update_or_create(
            product=self.product,
            supplier=self.supplier,
            defaults={'quantity': 5},
        )
        self.assertTrue(created)

        obj2, created2 = Stock.objects.update_or_create(
            product=self.product,
            supplier=self.supplier,
            defaults={'quantity': 15},
        )
        self.assertFalse(created2)
        self.assertEqual(obj2.quantity, 15)
        self.assertEqual(Stock.objects.count(), 1)
