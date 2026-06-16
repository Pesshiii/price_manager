from django.test import TestCase, override_settings

from pricing.engine import apply_raw_prices, apply_rules, compute_dest_value, reconcile_stock
from pricing.models import PricingRule, ProductPrice, Stock
from .fixtures import (
    make_entry as _make_entry,
    make_feed as _make_feed,
    make_price_type,
    make_product,
    make_supplier,
    price_column as _price_column,
    stock_column as _stock_column,
)


class ComputeDestValueTest(TestCase):
    def test_formula_applies_markup_and_increase(self):
        """formula: dest = source * (1 + markup/100) + increase."""
        rule = PricingRule(mode='formula', params={'markup': 20, 'increase': 10})
        self.assertAlmostEqual(compute_dest_value(rule, 100.0), 130.0)

    def test_fixed_returns_constant(self):
        """fixed: dest is a constant, independent of source."""
        rule = PricingRule(mode='fixed', params={'value': 999})
        self.assertAlmostEqual(compute_dest_value(rule, 100.0), 999.0)

    def test_malformed_mode_returns_none(self):
        """An unknown mode yields None so the caller can warn and skip."""
        rule = PricingRule(mode='bogus', params={})
        self.assertIsNone(compute_dest_value(rule, 100.0))


class ReconcileStockTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.present = make_product(sku='P1')
        self.absent = make_product(sku='P2')

    def test_absent_stock_untouched_when_not_full_inventory(self):
        """Default (partial) feed: present stock upserted, absent left as-is."""
        feed, mapping = _make_feed(self.supplier, is_full_inventory=False)
        _stock_column(mapping)
        Stock.objects.create(product=self.absent, supplier=self.supplier, quantity=99)
        _make_entry(feed, self.present, {'qty': '5'})

        reconcile_stock(feed)

        self.assertEqual(
            Stock.objects.get(product=self.present, supplier=self.supplier).quantity, 5
        )
        self.assertEqual(
            Stock.objects.get(product=self.absent, supplier=self.supplier).quantity, 99
        )

    def test_absent_stock_zeroed_when_full_inventory(self):
        """Full-inventory feed: absent supplier products are zeroed out."""
        feed, mapping = _make_feed(self.supplier, is_full_inventory=True)
        _stock_column(mapping)
        Stock.objects.create(product=self.absent, supplier=self.supplier, quantity=99)
        _make_entry(feed, self.present, {'qty': '5'})

        reconcile_stock(feed)

        self.assertEqual(
            Stock.objects.get(product=self.present, supplier=self.supplier).quantity, 5
        )
        self.assertEqual(
            Stock.objects.get(product=self.absent, supplier=self.supplier).quantity, 0
        )

    def test_no_stock_column_skips_zeroout_even_when_full_inventory(self):
        """A full-inventory mapping with no stock column carries no stock data,
        so it must not destroy absent products' stock."""
        feed, mapping = _make_feed(self.supplier, is_full_inventory=True)
        # deliberately no stock column configured on the mapping
        Stock.objects.create(product=self.absent, supplier=self.supplier, quantity=99)
        _make_entry(feed, self.present, {})

        reconcile_stock(feed)

        self.assertEqual(
            Stock.objects.get(product=self.absent, supplier=self.supplier).quantity, 99
        )

    def test_unparseable_stock_cell_preserves_prior_quantity(self):
        """A garbage stock cell skips the upsert rather than coercing to 0."""
        feed, mapping = _make_feed(self.supplier, is_full_inventory=False)
        _stock_column(mapping)
        Stock.objects.create(product=self.present, supplier=self.supplier, quantity=42)
        _make_entry(feed, self.present, {'qty': 'н/д'})

        reconcile_stock(feed)

        self.assertEqual(
            Stock.objects.get(product=self.present, supplier=self.supplier).quantity, 42
        )


class ApplyRawPricesTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.product = make_product()
        self.purchase_pt = make_price_type(name='закупочная', label='Закупочная')

    def test_price_column_creates_raw_price(self):
        """A price-role column produces a raw (rule=None) ProductPrice."""
        feed, mapping = _make_feed(self.supplier)
        _price_column(mapping, 'price', self.purchase_pt)
        _make_entry(feed, self.product, {'price': '150.00'})

        skipped = apply_raw_prices(feed)

        self.assertEqual(skipped, 0)
        pp = ProductPrice.objects.get()
        self.assertEqual(pp.product, self.product)
        self.assertEqual(pp.supplier, self.supplier)
        self.assertEqual(pp.price_type, self.purchase_pt)
        self.assertAlmostEqual(float(pp.value), 150.0)
        self.assertIsNone(pp.rule)

    def test_unparseable_price_counted_and_skipped(self):
        """A non-numeric price cell is skipped and counted, not written."""
        feed, mapping = _make_feed(self.supplier)
        _price_column(mapping, 'price', self.purchase_pt)
        _make_entry(feed, self.product, {'price': 'n/a'})

        skipped = apply_raw_prices(feed)

        self.assertEqual(skipped, 1)
        self.assertEqual(ProductPrice.objects.count(), 0)


class ApplyRawPricesFullInventoryTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.present = make_product(sku='P1')
        self.absent = make_product(sku='P2')
        self.purchase_pt = make_price_type(name='закупочная', label='Закупочная')

    def test_absent_prices_untouched_when_not_full_inventory(self):
        """Partial feed: absent product prices are left as-is."""
        feed, mapping = _make_feed(self.supplier, is_full_inventory=False)
        _price_column(mapping, 'price', self.purchase_pt)
        ProductPrice.objects.create(
            product=self.absent, supplier=self.supplier,
            price_type=self.purchase_pt, value=500, rule=None,
        )
        _make_entry(feed, self.present, {'price': '100'})

        apply_raw_prices(feed)

        self.assertTrue(
            ProductPrice.objects.filter(product=self.absent, supplier=self.supplier).exists()
        )

    def test_absent_prices_deleted_when_full_inventory(self):
        """Full-inventory feed: all ProductPrice (raw + derived) for absent product are deleted."""
        from pricing.models import PricingRule
        retail_pt = make_price_type(name='розничная', label='Розничная')
        rule = PricingRule.objects.create(
            supplier=self.supplier,
            source_price_type=self.purchase_pt,
            dest_price_type=retail_pt,
            mode='formula', params={'markup': 20, 'increase': 0}, priority=0,
        )
        feed, mapping = _make_feed(self.supplier, is_full_inventory=True)
        _price_column(mapping, 'price', self.purchase_pt)
        # absent has both raw and derived prices
        ProductPrice.objects.create(
            product=self.absent, supplier=self.supplier,
            price_type=self.purchase_pt, value=500, rule=None,
        )
        ProductPrice.objects.create(
            product=self.absent, supplier=self.supplier,
            price_type=retail_pt, value=600, rule=rule,
        )
        _make_entry(feed, self.present, {'price': '100'})

        apply_raw_prices(feed)

        self.assertFalse(
            ProductPrice.objects.filter(product=self.absent, supplier=self.supplier).exists()
        )
        # present product's price must survive
        self.assertTrue(
            ProductPrice.objects.filter(product=self.present, supplier=self.supplier).exists()
        )

    def test_no_price_columns_skips_deletion_even_when_full_inventory(self):
        """Full-inventory feed with no price columns carries no price data: no deletion."""
        feed, mapping = _make_feed(self.supplier, is_full_inventory=True)
        # deliberately no price column configured
        ProductPrice.objects.create(
            product=self.absent, supplier=self.supplier,
            price_type=self.purchase_pt, value=500, rule=None,
        )
        _make_entry(feed, self.present, {})

        apply_raw_prices(feed)

        self.assertTrue(
            ProductPrice.objects.filter(product=self.absent, supplier=self.supplier).exists()
        )

    def test_present_product_prices_survive_full_inventory(self):
        """Full-inventory feed: prices for present products are updated, not deleted."""
        feed, mapping = _make_feed(self.supplier, is_full_inventory=True)
        _price_column(mapping, 'price', self.purchase_pt)
        ProductPrice.objects.create(
            product=self.present, supplier=self.supplier,
            price_type=self.purchase_pt, value=100, rule=None,
        )
        _make_entry(feed, self.present, {'price': '200'})

        apply_raw_prices(feed)

        pp = ProductPrice.objects.get(product=self.present, supplier=self.supplier)
        self.assertAlmostEqual(float(pp.value), 200.0)


class ApplyRulesTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.product = make_product()
        self.src = make_price_type(name='закупочная', label='Закупочная')
        self.dest = make_price_type(name='розничная', label='Розничная')
        ProductPrice.objects.create(
            product=self.product, supplier=self.supplier,
            price_type=self.src, value=100, rule=None,
        )

    def _rule(self, **kwargs):
        defaults = dict(
            supplier=self.supplier, source_price_type=self.src,
            dest_price_type=self.dest, mode='formula',
            params={'markup': 20, 'increase': 10}, priority=0,
        )
        defaults.update(kwargs)
        return PricingRule.objects.create(**defaults)

    def test_formula_rule_creates_calculated_price(self):
        """dest = source * (1 + markup/100) + increase, with rule attribution."""
        rule = self._rule()

        apply_rules(self.supplier)

        calc = ProductPrice.objects.get(price_type=self.dest)
        self.assertAlmostEqual(float(calc.value), 130.0)
        self.assertEqual(calc.rule, rule)

    def test_future_rule_excluded_by_injected_now(self):
        """A rule with date_from after `now` does not apply — deterministic."""
        import datetime
        from django.utils import timezone

        now = timezone.make_aware(datetime.datetime(2026, 1, 1))
        self._rule(date_from=now + datetime.timedelta(days=10))

        apply_rules(self.supplier, now=now)

        self.assertFalse(ProductPrice.objects.filter(price_type=self.dest).exists())


@override_settings(SECURE_SSL_REDIRECT=False, CELERY_TASK_ALWAYS_EAGER=True)
class ApplyFeedPricingIntegrationTest(TestCase):
    """End-to-end, no mocks: feed + entries + FeedColumnMapping + PricingRule
    drive real ProductPrice and Stock rows through the adapter task."""

    def test_full_pipeline_produces_prices_and_stock(self):
        from pricing.tasks import apply_feed_pricing

        supplier = make_supplier()
        present = make_product(sku='P1')
        absent = make_product(sku='P2')
        purchase = make_price_type(name='закупочная', label='Закупочная')
        retail = make_price_type(name='розничная', label='Розничная')

        feed, mapping = _make_feed(supplier, is_full_inventory=True)
        _price_column(mapping, 'price', purchase)
        _stock_column(mapping, 'qty')
        rule = PricingRule.objects.create(
            supplier=supplier, source_price_type=purchase, dest_price_type=retail,
            mode='formula', params={'markup': 20, 'increase': 10}, priority=0,
        )

        Stock.objects.create(product=absent, supplier=supplier, quantity=99)
        _make_entry(feed, present, {'price': '100', 'qty': '5'})

        apply_feed_pricing(feed.pk)

        # Phase 1 — raw price (rule=None)
        raw = ProductPrice.objects.get(product=present, price_type=purchase)
        self.assertAlmostEqual(float(raw.value), 100.0)
        self.assertIsNone(raw.rule)

        # Phase 3 — calculated price (rule set)
        calc = ProductPrice.objects.get(product=present, price_type=retail)
        self.assertAlmostEqual(float(calc.value), 130.0)
        self.assertEqual(calc.rule, rule)

        # Phase 2 — stock: present upserted, absent zeroed (full-inventory)
        self.assertEqual(Stock.objects.get(product=present, supplier=supplier).quantity, 5)
        self.assertEqual(Stock.objects.get(product=absent, supplier=supplier).quantity, 0)

        # Phase 1 side-effect — prices for absent product deleted (full-inventory)
        self.assertFalse(ProductPrice.objects.filter(product=absent, supplier=supplier).exists())
