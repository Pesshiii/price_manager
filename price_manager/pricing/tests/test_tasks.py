from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from pricing.models import PriceType, PricingRule, ProductPrice, Stock
from pricing.tasks import apply_feed_pricing
from .fixtures import make_price_type, make_product, make_supplier


def _make_feed(supplier, feed_mapping=None):
    from dataframe.models import Dataframe
    from supplier_feed.models import FeedMapping, SupplierFeed

    df, _ = Dataframe.objects.get_or_create(
        name='Test Pipeline',
        defaults={
            'instructions': {
                'reader': {'func': 'read_csv', 'args': {}},
                'transforms': [],
            }
        },
    )
    if feed_mapping is None:
        feed_mapping = FeedMapping.objects.create(
            supplier=supplier,
            name='Test Mapping',
            supplier_sku_column='article',
            dataframe=df,
        )
    feed = SupplierFeed.objects.create(
        supplier=supplier,
        feed_mapping=feed_mapping,
        status='done',
    )
    return feed, feed_mapping


def _make_entry(feed, product, data):
    from supplier_feed.models import SupplierFeedEntry

    return SupplierFeedEntry.objects.create(
        feed=feed,
        product=product,
        supplier_sku=product.sku,
        data=data,
    )


@override_settings(SECURE_SSL_REDIRECT=False, CELERY_TASK_ALWAYS_EAGER=True)
class ApplyFeedPricingPricesTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.product = make_product()
        self.purchase_pt = make_price_type(name='закупочная', label='Закупочная')
        self.feed, self.feed_mapping = _make_feed(self.supplier)

    def test_price_columns_create_product_prices(self):
        """Price-role columns produce raw (rule=None) ProductPrice records."""
        _make_entry(self.feed, self.product, {'price': '150.00'})

        with patch('supplier_feed.models.FeedColumnMapping') as MockFCM:
            cm = MagicMock()
            cm.role = 'price'
            cm.column_name = 'price'
            cm.price_type = self.purchase_pt
            MockFCM.objects.filter.return_value.select_related.return_value = [cm]

            apply_feed_pricing(self.feed.pk)

        self.assertEqual(ProductPrice.objects.count(), 1)
        pp = ProductPrice.objects.get()
        self.assertEqual(pp.product, self.product)
        self.assertEqual(pp.supplier, self.supplier)
        self.assertEqual(pp.price_type, self.purchase_pt)
        self.assertAlmostEqual(float(pp.value), 150.0)
        self.assertIsNone(pp.rule)

    def test_invalid_price_value_skipped(self):
        """Non-numeric price values are silently skipped."""
        _make_entry(self.feed, self.product, {'price': 'n/a'})

        with patch('supplier_feed.models.FeedColumnMapping') as MockFCM:
            cm = MagicMock()
            cm.role = 'price'
            cm.column_name = 'price'
            cm.price_type = self.purchase_pt
            MockFCM.objects.filter.return_value.select_related.return_value = [cm]

            apply_feed_pricing(self.feed.pk)

        self.assertEqual(ProductPrice.objects.count(), 0)

    def test_no_entries_exits_early(self):
        """Task returns without error when feed has no matched entries."""
        apply_feed_pricing(self.feed.pk)
        self.assertEqual(ProductPrice.objects.count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False, CELERY_TASK_ALWAYS_EAGER=True)
class ApplyFeedPricingStockTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.product = make_product(sku='P1')
        self.absent_product = make_product(sku='P2')
        self.feed, _ = _make_feed(self.supplier)
        Stock.objects.create(product=self.absent_product, supplier=self.supplier, quantity=99)

    def test_stock_upserted_and_absent_zeroed(self):
        """Stock is upserted for feed products; absent supplier products are zeroed."""
        _make_entry(self.feed, self.product, {'qty': '5'})

        with patch('supplier_feed.models.FeedColumnMapping') as MockFCM:
            cm = MagicMock()
            cm.role = 'stock'
            cm.column_name = 'qty'
            cm.price_type = None
            MockFCM.objects.filter.return_value.select_related.return_value = [cm]

            apply_feed_pricing(self.feed.pk)

        stock_present = Stock.objects.get(product=self.product, supplier=self.supplier)
        self.assertEqual(stock_present.quantity, 5)

        stock_absent = Stock.objects.get(product=self.absent_product, supplier=self.supplier)
        self.assertEqual(stock_absent.quantity, 0)


@override_settings(SECURE_SSL_REDIRECT=False, CELERY_TASK_ALWAYS_EAGER=True)
class ApplyFeedPricingRulesTest(TestCase):
    def setUp(self):
        self.supplier = make_supplier()
        self.product = make_product()
        self.src_pt = make_price_type(name='закупочная', label='Закупочная')
        self.dest_pt = make_price_type(name='розничная', label='Розничная')
        self.feed, _ = _make_feed(self.supplier)
        ProductPrice.objects.create(
            product=self.product,
            supplier=self.supplier,
            price_type=self.src_pt,
            value=100,
            rule=None,
        )
        self.rule = PricingRule.objects.create(
            supplier=self.supplier,
            source_price_type=self.src_pt,
            dest_price_type=self.dest_pt,
            mode='formula',
            params={'markup': 20, 'increase': 10},
            priority=0,
        )

    def test_formula_rule_creates_calculated_price(self):
        """Formula rule: dest = source * (1 + markup/100) + increase."""
        _make_entry(self.feed, self.product, {})

        with patch('supplier_feed.models.FeedColumnMapping') as MockFCM:
            MockFCM.objects.filter.return_value.select_related.return_value = []

            apply_feed_pricing(self.feed.pk)

        calc = ProductPrice.objects.get(price_type=self.dest_pt)
        self.assertAlmostEqual(float(calc.value), 130.0)
        self.assertEqual(calc.rule, self.rule)

    def test_fixed_rule_creates_calculated_price(self):
        """Fixed rule sets dest to a constant value."""
        self.rule.mode = 'fixed'
        self.rule.params = {'value': 999}
        self.rule.save()

        _make_entry(self.feed, self.product, {})

        with patch('supplier_feed.models.FeedColumnMapping') as MockFCM:
            MockFCM.objects.filter.return_value.select_related.return_value = []

            apply_feed_pricing(self.feed.pk)

        calc = ProductPrice.objects.get(price_type=self.dest_pt)
        self.assertAlmostEqual(float(calc.value), 999.0)

    def test_price_range_filter_excludes_out_of_range(self):
        """Rule with price_from=200 should not apply to source price of 100."""
        self.rule.price_from = 200
        self.rule.save()

        _make_entry(self.feed, self.product, {})

        with patch('supplier_feed.models.FeedColumnMapping') as MockFCM:
            MockFCM.objects.filter.return_value.select_related.return_value = []

            apply_feed_pricing(self.feed.pk)

        self.assertFalse(ProductPrice.objects.filter(price_type=self.dest_pt).exists())
