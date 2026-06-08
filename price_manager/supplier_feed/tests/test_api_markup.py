"""Tests for FeedMarkupSet / FeedMarkupRule CRUD and apply_markups logic."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier_feed.models import (
    FeedMarkupRule,
    FeedMarkupSet,
    SupplierFeed,
    SupplierFeedEntry,
    STATUS_DONE,
)
from supplier_feed.markup import apply_markups
from .fixtures import make_feed_mapping, make_product, make_supplier

MSET_LIST = 'supplier_feed_api:feedmarkupset-list'
MSET_DETAIL = 'supplier_feed_api:feedmarkupset-detail'
MRULE_LIST = 'supplier_feed_api:feedmarkuprule-list'
MRULE_DETAIL = 'supplier_feed_api:feedmarkuprule-detail'


@override_settings(SECURE_SSL_REDIRECT=False)
class MarkupApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)

    def setUp(self):
        self.client.force_login(self.user)


# ── FeedMarkupSet CRUD ────────────────────────────────────────────────────────

class CreateMarkupSetTests(MarkupApiBase):
    def test_create_returns_201(self):
        resp = self.client.post(
            reverse(MSET_LIST),
            {'feed_mapping': self.mapping.pk, 'name': 'Розница', 'price_column': 'price', 'output_column': 'sale_price'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['price_column'], 'price')
        self.assertEqual(data['output_column'], 'sale_price')
        self.assertEqual(data['rules'], [])

    def test_list_filtered_by_mapping(self):
        other_mapping = make_feed_mapping(supplier=self.supplier, name='Другой')
        FeedMarkupSet.objects.create(feed_mapping=self.mapping, name='A', price_column='p', output_column='o')
        FeedMarkupSet.objects.create(feed_mapping=other_mapping, name='B', price_column='p', output_column='o')

        resp = self.client.get(reverse(MSET_LIST) + f'?mapping={self.mapping.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_anonymous_gets_401(self):
        self.client.logout()
        resp = self.client.get(reverse(MSET_LIST))
        self.assertEqual(resp.status_code, 401)


# ── FeedMarkupRule CRUD ───────────────────────────────────────────────────────

class CreateMarkupRuleTests(MarkupApiBase):
    def setUp(self):
        super().setUp()
        self.mset = FeedMarkupSet.objects.create(
            feed_mapping=self.mapping, name='Набор', price_column='price', output_column='sale'
        )

    def test_create_rule_returns_201(self):
        resp = self.client.post(
            reverse(MRULE_LIST),
            {
                'markup_set': self.mset.pk,
                'order': 10,
                'price_from': '0.00',
                'price_to': '1000.00',
                'markup': '15.00',
                'increase': '50.00',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['order'], 10)
        self.assertAlmostEqual(float(data['markup']), 15.0)

    def test_price_from_gt_price_to_returns_400(self):
        resp = self.client.post(
            reverse(MRULE_LIST),
            {
                'markup_set': self.mset.pk,
                'order': 1,
                'price_from': '2000.00',
                'price_to': '1000.00',
                'markup': '10.00',
                'increase': '0.00',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('price_to', resp.json())

    def test_open_ended_range_allowed(self):
        resp = self.client.post(
            reverse(MRULE_LIST),
            {'markup_set': self.mset.pk, 'order': 1, 'price_from': None, 'price_to': None, 'markup': '5', 'increase': '0'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)

    def test_list_filtered_by_markup_set(self):
        other_set = FeedMarkupSet.objects.create(
            feed_mapping=self.mapping, name='Другой', price_column='p', output_column='o'
        )
        FeedMarkupRule.objects.create(markup_set=self.mset, order=1, markup=10, increase=0)
        FeedMarkupRule.objects.create(markup_set=other_set, order=1, markup=5, increase=0)

        resp = self.client.get(reverse(MRULE_LIST) + f'?markup_set={self.mset.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)


# ── apply_markups logic ───────────────────────────────────────────────────────

class ApplyMarkupsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)
        cls.mset = FeedMarkupSet.objects.create(
            feed_mapping=cls.mapping, name='Набор', price_column='price', output_column='sale_price'
        )
        # Rule 1: price 0–1000, +10%, +50
        FeedMarkupRule.objects.create(markup_set=cls.mset, order=10, price_from=0, price_to=1000, markup=10, increase=50)
        # Rule 2: price 1000–∞, +5%, +0
        FeedMarkupRule.objects.create(markup_set=cls.mset, order=20, price_from=1000, price_to=None, markup=5, increase=0)

    def _make_feed(self):
        return SupplierFeed.objects.create(
            supplier=self.supplier, feed_mapping=self.mapping, status='partial'
        )

    def test_matched_entry_gets_calculated_price(self):
        feed = self._make_feed()
        product = make_product(sku='P-001')
        entry = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='X', product=product, data={'price': 500.0}
        )
        apply_markups(feed)
        entry.refresh_from_db()
        # 500 * 1.10 + 50 = 600
        self.assertAlmostEqual(entry.data['sale_price'], 600.0)

    def test_higher_price_uses_second_rule(self):
        feed = self._make_feed()
        product = make_product(sku='P-002')
        entry = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='Y', product=product, data={'price': 2000.0}
        )
        apply_markups(feed)
        entry.refresh_from_db()
        # 2000 * 1.05 + 0 = 2100
        self.assertAlmostEqual(entry.data['sale_price'], 2100.0)

    def test_no_rule_match_leaves_output_absent(self):
        feed = self._make_feed()
        product = make_product(sku='P-003')
        # price = -100 is below price_from=0 of rule 1, above None/rule 2's price_from=1000
        entry = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='Z', product=product, data={'price': -100.0}
        )
        apply_markups(feed)
        entry.refresh_from_db()
        self.assertNotIn('sale_price', entry.data)

    def test_missing_price_column_leaves_output_absent(self):
        feed = self._make_feed()
        product = make_product(sku='P-004')
        entry = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='W', product=product, data={'stock': 10}
        )
        apply_markups(feed)
        entry.refresh_from_db()
        self.assertNotIn('sale_price', entry.data)

    def test_unmatched_entry_skipped(self):
        feed = self._make_feed()
        # product=None — not matched
        entry = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='V', product=None, data={'price': 500.0}
        )
        apply_markups(feed)
        entry.refresh_from_db()
        self.assertNotIn('sale_price', entry.data)

    def test_no_markup_sets_is_noop(self):
        mapping_no_sets = make_feed_mapping(supplier=self.supplier, name='Без наценок')
        feed = SupplierFeed.objects.create(
            supplier=self.supplier, feed_mapping=mapping_no_sets, status='partial'
        )
        product = make_product(sku='P-005')
        entry = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='U', product=product, data={'price': 500.0}
        )
        apply_markups(feed)
        entry.refresh_from_db()
        self.assertNotIn('sale_price', entry.data)

    def test_order_priority_first_rule_wins(self):
        """When two rules overlap, lower order wins."""
        mset2 = FeedMarkupSet.objects.create(
            feed_mapping=self.mapping, name='Набор2', price_column='cost', output_column='out'
        )
        # Both cover 500; order=5 should win over order=99
        FeedMarkupRule.objects.create(markup_set=mset2, order=99, price_from=0, price_to=None, markup=20, increase=0)
        FeedMarkupRule.objects.create(markup_set=mset2, order=5, price_from=0, price_to=None, markup=10, increase=0)

        feed = self._make_feed()
        product = make_product(sku='P-006')
        entry = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='T', product=product, data={'cost': 100.0}
        )
        apply_markups(feed)
        entry.refresh_from_db()
        # order=5 rule: 100 * 1.10 = 110
        self.assertAlmostEqual(entry.data['out'], 110.0)


# ── done transition triggers apply_markups ───────────────────────────────────

class DoneTransitionMarkupTests(TestCase):
    """Integration: markup applied automatically when feed transitions to done via resolve."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u2', password='p')
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)
        mset = FeedMarkupSet.objects.create(
            feed_mapping=cls.mapping, name='Н', price_column='price', output_column='sale'
        )
        FeedMarkupRule.objects.create(markup_set=mset, order=1, price_from=None, price_to=None, markup=10, increase=0)

    def setUp(self):
        self.client.force_login(self.user)

    def test_markup_applied_on_done_via_resolve(self):
        product = make_product(sku='D-001')
        feed = SupplierFeed.objects.create(
            supplier=self.supplier, feed_mapping=self.mapping, status='partial'
        )
        # One already-matched entry (should get markup recalculated at done)
        matched = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='M1', product=product, data={'price': 200.0}
        )
        # One queued entry — resolving it will empty the queue → done
        queued = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='Q1', product=None, data={'price': 300.0}
        )

        url = reverse('supplier_feed_api:supplierfeed-resolve', args=[feed.pk, queued.pk])
        resp = self.client.post(url, {'product_id': product.pk}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_DONE)

        matched.refresh_from_db()
        self.assertAlmostEqual(matched.data['sale'], 220.0)  # 200 * 1.10

        queued.refresh_from_db()
        self.assertAlmostEqual(queued.data['sale'], 330.0)   # 300 * 1.10
