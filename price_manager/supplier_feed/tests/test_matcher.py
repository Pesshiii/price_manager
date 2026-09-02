"""Tests for supplier_feed.matcher.run_matching — behavior via public interface.

No embedding-based matching remains: rows either hit a cached SupplierLink or
land straight in the manual-review queue with zero auto-suggested candidates.
"""
from __future__ import annotations

from django.test import TestCase

from product.models import Product
from supplier_feed.matcher import run_matching
from supplier_feed.models import (
    SupplierFeed,
    SupplierFeedEntry,
    SupplierLink,
)
from .fixtures import make_feed_mapping, make_supplier


def _make_product(name: str, number: str) -> Product:
    return Product.objects.create(name=name, number=number, pim_id=f'PIM-{number}')


def _make_feed(supplier=None, mapping=None) -> SupplierFeed:
    if supplier is None:
        supplier = make_supplier()
    if mapping is None:
        mapping = make_feed_mapping(
            supplier=supplier,
            supplier_sku_column='article',
            identity_columns=['name'],
            variable_columns=['price'],
        )
    return SupplierFeed.objects.create(
        supplier=supplier,
        feed_mapping=mapping,
        status='processing',
    )


# ── Cycle 1: SupplierLink lookup ─────────────────────────────────────────────

class SupplierLinkMatchTests(TestCase):
    """Branch 1: rows already in SupplierLink → instant match."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier A')
        self.product = _make_product('Дрель', 'P-001')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            identity_columns=['name'],
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

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 1)
        self.assertEqual(stats['queued'], 0)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-001')
        self.assertEqual(entry.product_id, self.product.pk)

    def test_sku_match_stores_variable_data(self):
        """Variable columns are saved to entry.data."""
        rows = [{'article': 'SKU-001', 'name': 'Дрель', 'price': '750'}]

        run_matching(self.feed, rows)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-001')
        self.assertEqual(entry.data.get('price'), '750')

    def test_sku_match_stores_identity_data(self):
        """Identity columns are merged into entry.data alongside variable columns."""
        rows = [{'article': 'SKU-001', 'name': 'Дрель', 'price': '750'}]

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

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 2)
        self.assertEqual(stats['queued'], 0)
        self.assertEqual(SupplierFeedEntry.objects.filter(feed=self.feed).count(), 2)


# ── Cycle 2: Queue path (no cached link) ─────────────────────────────────────

class QueueTests(TestCase):
    """Branch 2: no SupplierLink → queued with zero auto-suggested candidates."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier C')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            identity_columns=['name'],
            variable_columns=[],
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )

    def test_unlinked_row_queues_entry_with_no_candidates(self):
        """No cached link → entry.product=None, no candidates, no SupplierLink."""
        rows = [{'article': 'UNKNOWN-SKU', 'name': 'Утюг'}]

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 0)
        self.assertEqual(stats['queued'], 1)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='UNKNOWN-SKU')
        self.assertIsNone(entry.product_id)
        self.assertEqual(entry.match_candidates, [])
        self.assertIsNone(entry.best_score)

        self.assertFalse(
            SupplierLink.objects.filter(
                supplier=self.supplier, supplier_sku='UNKNOWN-SKU'
            ).exists()
        )


# ── Cycle 3: Mixed batch ──────────────────────────────────────────────────────

class MixedBatchTests(TestCase):
    """Branch 3: batch with linked + unlinked rows → correct totals."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier D')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            identity_columns=['name'],
            variable_columns=[],
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

    def test_mixed_batch_returns_correct_stats_includes_skipped_key(self):
        """run_matching return dict must include 'skipped' key."""
        stats = run_matching(self.feed, [])
        self.assertIn('skipped', stats)

    def test_mixed_batch_returns_correct_stats(self):
        """1 linked + 2 unlinked → matched=1, queued=2."""
        rows = [
            {'article': 'SKU-A', 'name': 'Товар A'},   # linked
            {'article': 'SKU-B', 'name': 'Товар B'},   # queued
            {'article': 'SKU-C', 'name': 'Товар C'},   # queued
        ]

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 1)
        self.assertEqual(stats['queued'], 2)

        queued_entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-C')
        self.assertIsNone(queued_entry.product_id)


# ── Cycle 4: Ignore-link ─────────────────────────────────────────────────────

class IgnoreLinkTests(TestCase):
    """Branch 4: SupplierLink with product=None (ignore-link) → entry skipped."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier E')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            identity_columns=['name'],
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

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats.get('skipped', 0), 1)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='IGN-001')
        self.assertTrue(entry.skipped)
        self.assertIsNone(entry.product_id)

    def test_ignore_link_does_not_count_as_matched(self):
        """Ignored row must NOT increment the matched counter."""
        rows = [{'article': 'IGN-001', 'name': 'Что-то', 'price': '100'}]

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

        stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 1)
        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='REG-001')
        self.assertEqual(entry.product_id, product.pk)
