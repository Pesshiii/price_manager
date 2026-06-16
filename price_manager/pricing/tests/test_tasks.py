"""Adapter-level tests for the `apply_feed_pricing` Celery task.

These exercise the task against real feed/mapping/entry/rule objects (no mocks)
— the engine internals have their own focused tests in `test_engine.py`. The
task's job is orchestration + the transaction boundary; here we assert that a
finished feed end-to-end yields the right ProductPrice/Stock rows.
"""
from django.test import TestCase, override_settings

from pricing.models import PricingRule, ProductPrice, Stock
from pricing.tasks import apply_feed_pricing
from .fixtures import (
    make_entry, make_feed, make_price_type, make_product, make_supplier,
    price_column, stock_column,
)


@override_settings(SECURE_SSL_REDIRECT=False, CELERY_TASK_ALWAYS_EAGER=True)
class ApplyFeedPricingPricesTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.product = make_product()
        self.purchase_pt = make_price_type(name='закупочная', label='Закупочная')

    def test_price_column_creates_raw_product_price(self):
        feed, mapping = make_feed(self.supplier)
        price_column(mapping, 'price', self.purchase_pt)
        make_entry(feed, self.product, {'price': '150.00'})

        apply_feed_pricing(feed.pk)

        pp = ProductPrice.objects.get()
        self.assertEqual(pp.product, self.product)
        self.assertEqual(pp.supplier, self.supplier)
        self.assertEqual(pp.price_type, self.purchase_pt)
        self.assertAlmostEqual(float(pp.value), 150.0)
        self.assertIsNone(pp.rule)

    def test_invalid_price_value_skipped(self):
        feed, mapping = make_feed(self.supplier)
        price_column(mapping, 'price', self.purchase_pt)
        make_entry(feed, self.product, {'price': 'n/a'})

        apply_feed_pricing(feed.pk)

        self.assertEqual(ProductPrice.objects.count(), 0)

    def test_no_entries_exits_cleanly(self):
        feed, _ = make_feed(self.supplier)
        apply_feed_pricing(feed.pk)
        self.assertEqual(ProductPrice.objects.count(), 0)

    def test_missing_feed_is_noop(self):
        apply_feed_pricing(999999)  # does not raise
        self.assertEqual(ProductPrice.objects.count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False, CELERY_TASK_ALWAYS_EAGER=True)
class ApplyFeedPricingStockTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.product = make_product(sku='P1')
        self.absent_product = make_product(sku='P2')
        Stock.objects.create(product=self.absent_product, supplier=self.supplier, quantity=99)

    def test_absent_stock_zeroed_for_full_inventory_feed(self):
        feed, mapping = make_feed(self.supplier, is_full_inventory=True)
        stock_column(mapping, 'qty')
        make_entry(feed, self.product, {'qty': '5'})

        apply_feed_pricing(feed.pk)

        self.assertEqual(
            Stock.objects.get(product=self.product, supplier=self.supplier).quantity, 5
        )
        self.assertEqual(
            Stock.objects.get(product=self.absent_product, supplier=self.supplier).quantity, 0
        )

    def test_absent_stock_preserved_for_partial_feed(self):
        feed, mapping = make_feed(self.supplier, is_full_inventory=False)
        stock_column(mapping, 'qty')
        make_entry(feed, self.product, {'qty': '5'})

        apply_feed_pricing(feed.pk)

        self.assertEqual(
            Stock.objects.get(product=self.product, supplier=self.supplier).quantity, 5
        )
        self.assertEqual(
            Stock.objects.get(product=self.absent_product, supplier=self.supplier).quantity, 99
        )


@override_settings(SECURE_SSL_REDIRECT=False, CELERY_TASK_ALWAYS_EAGER=True)
class ApplyFeedPricingRulesTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.product = make_product()
        self.src_pt = make_price_type(name='закупочная', label='Закупочная')
        self.dest_pt = make_price_type(name='розничная', label='Розничная')
        ProductPrice.objects.create(
            product=self.product, supplier=self.supplier,
            price_type=self.src_pt, value=100, rule=None,
        )
        self.rule = PricingRule.objects.create(
            supplier=self.supplier, source_price_type=self.src_pt,
            dest_price_type=self.dest_pt, mode='formula',
            params={'markup': 20, 'increase': 10}, priority=0,
        )

    def _run(self):
        feed, _ = make_feed(self.supplier)
        make_entry(feed, self.product, {})
        apply_feed_pricing(feed.pk)

    def test_formula_rule_creates_calculated_price(self):
        self._run()
        calc = ProductPrice.objects.get(price_type=self.dest_pt)
        self.assertAlmostEqual(float(calc.value), 130.0)
        self.assertEqual(calc.rule, self.rule)

    def test_fixed_rule_creates_calculated_price(self):
        self.rule.mode = 'fixed'
        self.rule.params = {'value': 999}
        self.rule.save()

        self._run()

        calc = ProductPrice.objects.get(price_type=self.dest_pt)
        self.assertAlmostEqual(float(calc.value), 999.0)

    def test_price_range_filter_excludes_out_of_range(self):
        self.rule.price_from = 200
        self.rule.save()

        self._run()

        self.assertFalse(ProductPrice.objects.filter(price_type=self.dest_pt).exists())
