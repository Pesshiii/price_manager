"""Tests for supplier_feed.matcher.run_matching — behavior via public interface.

Each class covers one algorithmic branch. _find_candidates is always mocked so
no live PostgreSQL pg_trgm extension or rapidfuzz scoring is required.
"""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from product.models import Brand, Category, Product
from supplier_feed.matcher import run_matching
from supplier_feed.models import (
    SupplierFeed,
    SupplierFeedEntry,
    SupplierLink,
)
from .fixtures import make_feed_mapping, make_supplier

FIND_CANDIDATES_PATH = 'supplier_feed.matcher._find_candidates'


def _make_product(name: str, sku: str) -> Product:
    brand, _ = Brand.objects.get_or_create(name='TestBrand', defaults={'slug': 'testbrand'})
    cat, _ = Category.objects.get_or_create(name='TestCat', defaults={'slug': 'testcat'})
    return Product.objects.create(name=name, sku=sku, brand=brand, category=cat)


def _candidate(product: Product, score: float) -> dict:
    return {
        'product_id': product.pk,
        'score': score,
        'name': product.name,
        'sku': product.sku,
        'category': 'TestCat',
        'brand': 'TestBrand',
    }


# ── Cycle 1: SupplierLink lookup ─────────────────────────────────────────────

class SupplierLinkMatchTests(TestCase):
    """Branch 1: rows already in SupplierLink → instant match, no text search."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier A')
        self.product = _make_product('Дрель', 'P-001')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            name_column='name',
            variable_columns=['price'],
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )
        SupplierLink.objects.create(
            supplier=self.supplier,
            supplier_sku='SKU-001',
            product=self.product,
        )

    def test_sku_match_creates_entry_with_product(self):
        """Known SKU → entry.product set, stats show matched=1, queued=0."""
        rows = [{'article': 'SKU-001', 'name': 'Дрель', 'price': '500'}]

        with patch(FIND_CANDIDATES_PATH) as mock_find:
            stats = run_matching(self.feed, rows)

        mock_find.assert_not_called()

        self.assertEqual(stats['matched'], 1)
        self.assertEqual(stats['queued'], 0)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-001')
        self.assertEqual(entry.product_id, self.product.pk)

    def test_sku_match_stores_variable_data(self):
        """Variable columns are saved to entry.data."""
        rows = [{'article': 'SKU-001', 'name': 'Дрель', 'price': '750'}]

        with patch(FIND_CANDIDATES_PATH):
            run_matching(self.feed, rows)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-001')
        self.assertEqual(entry.data.get('price'), '750')

    def test_sku_match_stores_name_data(self):
        """name_column value is stored in entry.data."""
        rows = [{'article': 'SKU-001', 'name': 'Дрель', 'price': '750'}]

        with patch(FIND_CANDIDATES_PATH):
            run_matching(self.feed, rows)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-001')
        self.assertEqual(entry.data.get('name'), 'Дрель')

    def test_multiple_linked_skus_all_matched(self):
        """Two known SKUs → both entries created, matched=2."""
        product2 = _make_product('Перфоратор', 'P-002')
        SupplierLink.objects.create(
            supplier=self.supplier,
            supplier_sku='SKU-002',
            product=product2,
        )
        rows = [
            {'article': 'SKU-001', 'name': 'Дрель', 'price': '500'},
            {'article': 'SKU-002', 'name': 'Перфоратор', 'price': '1200'},
        ]

        with patch(FIND_CANDIDATES_PATH) as mock_find:
            stats = run_matching(self.feed, rows)

        mock_find.assert_not_called()
        self.assertEqual(stats['matched'], 2)
        self.assertEqual(stats['queued'], 0)
        self.assertEqual(SupplierFeedEntry.objects.filter(feed=self.feed).count(), 2)


# ── Cycle 2: Text auto-match ──────────────────────────────────────────────────

class TextAutoMatchTests(TestCase):
    """Branch 2: no SupplierLink, score >= auto_match_threshold → auto-match."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier B')
        self.product = _make_product('Шуруповерт', 'P-010')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            name_column='name',
            auto_match_threshold=0.92,
            low_match_threshold=0.5,
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )

    @patch(FIND_CANDIDATES_PATH)
    def test_high_score_creates_supplier_link(self, mock_find):
        """Score >= auto_match_threshold → entry.product set AND SupplierLink created."""
        mock_find.return_value = [_candidate(self.product, 0.95)]
        rows = [{'article': 'NEW-SKU', 'name': 'Шуруповерт'}]

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 1)
        self.assertEqual(stats['queued'], 0)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='NEW-SKU')
        self.assertEqual(entry.product_id, self.product.pk)
        self.assertEqual(entry.match_candidates, [])

        link = SupplierLink.objects.get(supplier=self.supplier, supplier_sku='NEW-SKU')
        self.assertEqual(link.product_id, self.product.pk)

    @patch(FIND_CANDIDATES_PATH)
    def test_find_candidates_called_with_entry_name(self, mock_find):
        """_find_candidates is called with the name column value and low_thresh."""
        mock_find.return_value = [_candidate(self.product, 0.95)]
        rows = [{'article': 'NEW-SKU', 'name': 'Шуруповерт'}]

        run_matching(self.feed, rows)

        mock_find.assert_called_once_with('Шуруповерт', 0.5)


# ── Cycle 3: Queue path ───────────────────────────────────────────────────────

class TextQueueTests(TestCase):
    """Branch 3: no SupplierLink, score < auto_match_threshold → queued."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier C')
        self.product = _make_product('Фен', 'P-020')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            name_column='name',
            auto_match_threshold=0.92,
            low_match_threshold=0.5,
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )

    @patch(FIND_CANDIDATES_PATH)
    def test_low_score_queues_entry_with_candidates(self, mock_find):
        """Score < auto_match_threshold → entry.product=None, match_candidates populated."""
        mock_find.return_value = [_candidate(self.product, 0.75)]
        rows = [{'article': 'UNKNOWN-SKU', 'name': 'Утюг'}]

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 0)
        self.assertEqual(stats['queued'], 1)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='UNKNOWN-SKU')
        self.assertIsNone(entry.product_id)
        self.assertEqual(len(entry.match_candidates), 1)
        first = entry.match_candidates[0]
        self.assertEqual(first['product_id'], self.product.pk)
        self.assertIn('score', first)
        self.assertEqual(first['name'], self.product.name)
        self.assertEqual(first['sku'], self.product.sku)
        self.assertEqual(first['category'], 'TestCat')
        self.assertEqual(first['brand'], 'TestBrand')

    @patch(FIND_CANDIDATES_PATH)
    def test_no_supplier_link_created_for_queued_entry(self, mock_find):
        """Low-score match must NOT create a SupplierLink."""
        mock_find.return_value = [_candidate(self.product, 0.75)]
        rows = [{'article': 'UNKNOWN-SKU', 'name': 'Утюг'}]

        run_matching(self.feed, rows)

        self.assertFalse(
            SupplierLink.objects.filter(
                supplier=self.supplier, supplier_sku='UNKNOWN-SKU'
            ).exists()
        )

    @patch(FIND_CANDIDATES_PATH)
    def test_queued_entry_has_best_score(self, mock_find):
        """Queued entry with candidates must have best_score populated."""
        mock_find.return_value = [_candidate(self.product, 0.75)]
        rows = [{'article': 'SCORE-SKU', 'name': 'Утюг'}]

        run_matching(self.feed, rows)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SCORE-SKU')
        self.assertAlmostEqual(entry.best_score, 0.75, places=3)

    @patch(FIND_CANDIDATES_PATH)
    def test_no_candidates_queues_with_null_best_score(self, mock_find):
        """When _find_candidates returns [], entry is queued with empty candidates and best_score=None."""
        mock_find.return_value = []
        rows = [{'article': 'GHOST-SKU', 'name': 'Что-то'}]

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['queued'], 1)
        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='GHOST-SKU')
        self.assertIsNone(entry.product_id)
        self.assertEqual(entry.match_candidates, [])
        self.assertIsNone(entry.best_score)


# ── Cycle 4: Ignore-link ─────────────────────────────────────────────────────

class IgnoreLinkTests(TestCase):
    """Branch 4: SupplierLink with product=None (ignore-link) → entry skipped."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier E')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            name_column='name',
            variable_columns=['price'],
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )
        SupplierLink.objects.create(
            supplier=self.supplier,
            supplier_sku='IGN-001',
            product=None,
        )

    def test_ignore_link_creates_skipped_entry(self):
        """Row matching an ignore-link → entry.skipped=True, not matched."""
        rows = [{'article': 'IGN-001', 'name': 'Что-то', 'price': '100'}]

        with patch(FIND_CANDIDATES_PATH) as mock_find:
            stats = run_matching(self.feed, rows)

        mock_find.assert_not_called()
        self.assertEqual(stats.get('skipped', 0), 1)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='IGN-001')
        self.assertTrue(entry.skipped)
        self.assertIsNone(entry.product_id)

    def test_ignore_link_does_not_count_as_matched(self):
        """Ignored row must NOT increment the matched counter."""
        rows = [{'article': 'IGN-001', 'name': 'Что-то', 'price': '100'}]

        with patch(FIND_CANDIDATES_PATH):
            stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 0)

    def test_normal_link_still_auto_matches(self):
        """Regression: a normal SupplierLink (product≠None) still resolves instantly."""
        product = _make_product('Дрель', 'P-REG-001')
        SupplierLink.objects.create(
            supplier=self.supplier,
            supplier_sku='REG-001',
            product=product,
        )
        rows = [{'article': 'REG-001', 'name': 'Дрель', 'price': '500'}]

        with patch(FIND_CANDIDATES_PATH) as mock_find:
            stats = run_matching(self.feed, rows)

        mock_find.assert_not_called()
        self.assertEqual(stats['matched'], 1)
        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='REG-001')
        self.assertEqual(entry.product_id, product.pk)


# ── Cycle 5: Mixed batch ──────────────────────────────────────────────────────

class MixedBatchTests(TestCase):
    """Branch 5: batch with linked + auto-match + queued → correct totals."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier D')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            name_column='name',
            auto_match_threshold=0.92,
            low_match_threshold=0.5,
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )

        self.product_a = _make_product('Товар A', 'PA')
        SupplierLink.objects.create(
            supplier=self.supplier, supplier_sku='SKU-A', product=self.product_a
        )
        self.product_b = _make_product('Товар B', 'PB')
        self.product_c = _make_product('Товар C', 'PC')

    def test_mixed_batch_returns_correct_stats_includes_skipped_key(self):
        """run_matching return dict must include 'skipped' key."""
        with patch(FIND_CANDIDATES_PATH, return_value=[]):
            stats = run_matching(self.feed, [])
        self.assertIn('skipped', stats)

    @patch(FIND_CANDIDATES_PATH)
    def test_mixed_batch_returns_correct_stats(self, mock_find):
        """1 linked + 1 auto-match + 1 queued → matched=2, queued=1."""
        rows = [
            {'article': 'SKU-A', 'name': 'Товар A'},
            {'article': 'SKU-B', 'name': 'Товар B'},
            {'article': 'SKU-C', 'name': 'Товар C'},
        ]

        def side_effect(name, low_thresh):
            if 'Товар B' in name:
                return [_candidate(self.product_b, 0.95)]
            return [_candidate(self.product_c, 0.60)]

        mock_find.side_effect = side_effect

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 2)
        self.assertEqual(stats['queued'], 1)

        self.assertTrue(
            SupplierLink.objects.filter(
                supplier=self.supplier, supplier_sku='SKU-B'
            ).exists()
        )
        queued_entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-C')
        self.assertIsNone(queued_entry.product_id)
