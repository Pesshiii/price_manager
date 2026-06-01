"""Tests for supplier_feed.matcher.run_matching — behavior via public interface.

Each class covers one algorithmic branch.  The embedder (embed_query) is always
mocked so no live Ollama instance is required.  pgvector CosineDistance is
exercised through real Product rows in the test database.
"""
from __future__ import annotations

from unittest.mock import patch, call

from django.test import TestCase

from product.models import Brand, Category, Product
from supplier_feed.matcher import run_matching
from supplier_feed.models import (
    SupplierFeed,
    SupplierFeedEntry,
    SupplierLink,
)
from .fixtures import make_feed_mapping, make_supplier

EMBED_PATH = 'supplier_feed.matcher.embed_query'

DIM = 256  # must match PRODUCT_EMBEDDING_DIM


def _unit_vec(idx: int = 0) -> list[float]:
    """Unit vector with 1.0 at position `idx`, 0.0 elsewhere."""
    v = [0.0] * DIM
    v[idx] = 1.0
    return v


def _make_product(name: str, sku: str, embedding: list[float] | None = None) -> Product:
    brand, _ = Brand.objects.get_or_create(name='TestBrand', defaults={'slug': 'testbrand'})
    cat, _ = Category.objects.get_or_create(name='TestCat', defaults={'slug': 'testcat'})
    p = Product.objects.create(name=name, sku=sku, brand=brand, category=cat)
    if embedding is not None:
        p.embedding = embedding
        p.save(update_fields=['embedding'])
    return p


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
    """Branch 1: rows already in SupplierLink → instant match, no embedder call."""

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

        with patch(EMBED_PATH) as mock_embed:
            stats = run_matching(self.feed, rows)

        # embed_query must never be called for already-linked SKUs
        mock_embed.assert_not_called()

        self.assertEqual(stats['matched'], 1)
        self.assertEqual(stats['queued'], 0)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-001')
        self.assertEqual(entry.product_id, self.product.pk)

    def test_sku_match_stores_variable_data(self):
        """Variable columns are saved to entry.data."""
        rows = [{'article': 'SKU-001', 'name': 'Дрель', 'price': '750'}]

        with patch(EMBED_PATH):
            run_matching(self.feed, rows)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-001')
        self.assertEqual(entry.data.get('price'), '750')

    def test_sku_match_stores_identity_data(self):
        """Identity columns are merged into entry.data alongside variable columns."""
        rows = [{'article': 'SKU-001', 'name': 'Дрель', 'price': '750'}]

        with patch(EMBED_PATH):
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

        with patch(EMBED_PATH) as mock_embed:
            stats = run_matching(self.feed, rows)

        mock_embed.assert_not_called()
        self.assertEqual(stats['matched'], 2)
        self.assertEqual(stats['queued'], 0)
        self.assertEqual(SupplierFeedEntry.objects.filter(feed=self.feed).count(), 2)


# ── Cycle 2: Vector auto-match ────────────────────────────────────────────────

class VectorAutoMatchTests(TestCase):
    """Branch 2: no SupplierLink, embedding score ≥ threshold → auto-match."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier B')
        # Product with embedding pointing in direction [1, 0, 0, ...]
        self.product = _make_product('Шуруповерт', 'P-010', embedding=_unit_vec(0))
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            identity_columns=['name'],
            variable_columns=[],
            auto_match_threshold=0.92,
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )

    def test_high_similarity_creates_supplier_link(self):
        """Score ≥ threshold → entry.product set AND SupplierLink created."""
        rows = [{'article': 'NEW-SKU', 'name': 'Шуруповерт'}]

        # Query embedding is identical to product embedding → cosine distance = 0
        with patch(EMBED_PATH, return_value=_unit_vec(0)):
            stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 1)
        self.assertEqual(stats['queued'], 0)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='NEW-SKU')
        self.assertEqual(entry.product_id, self.product.pk)
        self.assertEqual(entry.match_candidates, [])

        # Permanent link created for future feeds
        link = SupplierLink.objects.get(supplier=self.supplier, supplier_sku='NEW-SKU')
        self.assertEqual(link.product_id, self.product.pk)

    def test_embed_query_called_with_identity_text(self):
        """Identity columns are joined and passed to embed_query."""
        rows = [{'article': 'NEW-SKU', 'name': 'Шуруповерт'}]

        with patch(EMBED_PATH, return_value=_unit_vec(0)) as mock_embed:
            run_matching(self.feed, rows)

        mock_embed.assert_called_once_with('Шуруповерт')


# ── Cycle 3: Queue path ───────────────────────────────────────────────────────

class VectorQueueTests(TestCase):
    """Branch 3: no SupplierLink, embedding score < threshold → queued."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier C')
        # Product pointing [1, 0, 0, ...]
        self.product = _make_product('Фен', 'P-020', embedding=_unit_vec(0))
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            identity_columns=['name'],
            variable_columns=[],
            auto_match_threshold=0.92,
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )

    def test_low_similarity_queues_entry_with_candidates(self):
        """Score < threshold → entry.product=None, match_candidates populated."""
        rows = [{'article': 'UNKNOWN-SKU', 'name': 'Утюг'}]

        # Query vector perpendicular to product → cosine distance = 1, similarity = 0
        with patch(EMBED_PATH, return_value=_unit_vec(1)):
            stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 0)
        self.assertEqual(stats['queued'], 1)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='UNKNOWN-SKU')
        self.assertIsNone(entry.product_id)

        # Candidates list contains the product with its score and catalogue fields
        self.assertGreater(len(entry.match_candidates), 0)
        first = entry.match_candidates[0]
        self.assertEqual(first['product_id'], self.product.pk)
        self.assertIn('score', first)
        self.assertEqual(first['name'], self.product.name)
        self.assertEqual(first['sku'], self.product.sku)
        self.assertEqual(first['category'], 'TestCat')
        self.assertEqual(first['brand'], 'TestBrand')

    def test_no_supplier_link_created_for_queued_entry(self):
        """Low-similarity match must NOT create a SupplierLink."""
        rows = [{'article': 'UNKNOWN-SKU', 'name': 'Утюг'}]

        with patch(EMBED_PATH, return_value=_unit_vec(1)):
            run_matching(self.feed, rows)

        self.assertFalse(
            SupplierLink.objects.filter(
                supplier=self.supplier, supplier_sku='UNKNOWN-SKU'
            ).exists()
        )

    def test_low_similarity_entry_has_best_score_set(self):
        """Queued entry with candidates must have best_score populated."""
        rows = [{'article': 'SCORE-SKU', 'name': 'Утюг'}]

        with patch(EMBED_PATH, return_value=_unit_vec(1)):
            run_matching(self.feed, rows)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SCORE-SKU')
        self.assertIsNotNone(entry.best_score)
        # Perpendicular vectors → cosine similarity = 0
        self.assertAlmostEqual(entry.best_score, 0.0, places=3)

    def test_no_products_with_embeddings_still_queues(self):
        """When no products have embeddings, entry is queued with empty candidates."""
        self.product.embedding = None
        self.product.save(update_fields=['embedding'])

        rows = [{'article': 'GHOST-SKU', 'name': 'Что-то'}]

        with patch(EMBED_PATH, return_value=_unit_vec(0)):
            stats = run_matching(self.feed, rows)

        self.assertEqual(stats['queued'], 1)
        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='GHOST-SKU')
        self.assertIsNone(entry.product_id)
        self.assertEqual(entry.match_candidates, [])

    def test_no_products_with_embeddings_gives_null_best_score(self):
        """Entry with no candidates must have best_score=None (anomaly marker)."""
        self.product.embedding = None
        self.product.save(update_fields=['embedding'])

        rows = [{'article': 'NULL-SCORE-SKU', 'name': 'Что-то'}]

        with patch(EMBED_PATH, return_value=_unit_vec(0)):
            run_matching(self.feed, rows)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='NULL-SCORE-SKU')
        self.assertIsNone(entry.best_score)


# ── Cycle 4: Mixed batch ──────────────────────────────────────────────────────

class MixedBatchTests(TestCase):
    """Branch 4: batch with linked + auto-match + queued rows → correct totals."""

    def setUp(self):
        self.supplier = make_supplier(name='Supplier D')
        self.mapping = make_feed_mapping(
            supplier=self.supplier,
            supplier_sku_column='article',
            identity_columns=['name'],
            variable_columns=[],
            auto_match_threshold=0.92,
        )
        self.feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status='processing',
        )

        # product_a: will be matched via SupplierLink
        self.product_a = _make_product('Товар A', 'PA')
        SupplierLink.objects.create(
            supplier=self.supplier, supplier_sku='SKU-A', product=self.product_a
        )

        # product_b: will be auto-matched via embedding (vec index 2)
        self.product_b = _make_product('Товар B', 'PB', embedding=_unit_vec(2))

        # product_c: exists but only as low-similarity candidate (vec index 3)
        self.product_c = _make_product('Товар C', 'PC', embedding=_unit_vec(3))

    def test_mixed_batch_returns_correct_stats_includes_skipped_key(self):
        """run_matching return dict must include 'skipped' key."""
        rows = []
        with patch(EMBED_PATH, return_value=_unit_vec(0)):
            stats = run_matching(self.feed, rows)
        self.assertIn('skipped', stats)

    def test_mixed_batch_returns_correct_stats(self):
        """1 linked + 1 auto-match + 1 queued → matched=2, queued=1."""
        rows = [
            {'article': 'SKU-A', 'name': 'Товар A'},   # linked
            {'article': 'SKU-B', 'name': 'Товар B'},   # auto-match (vec[2] ≈ product_b)
            {'article': 'SKU-C', 'name': 'Товар C'},   # queued   (vec[4] ≠ anything close)
        ]

        def fake_embed(text):
            if 'Товар B' in text:
                return _unit_vec(2)   # identical to product_b → distance 0 → auto-match
            return _unit_vec(4)       # perpendicular to everything → queued

        with patch(EMBED_PATH, side_effect=fake_embed):
            stats = run_matching(self.feed, rows)

        self.assertEqual(stats['matched'], 2)
        self.assertEqual(stats['queued'], 1)

        # Auto-match created a SupplierLink
        self.assertTrue(
            SupplierLink.objects.filter(
                supplier=self.supplier, supplier_sku='SKU-B'
            ).exists()
        )
        # Queued entry has product=None
        queued_entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='SKU-C')
        self.assertIsNone(queued_entry.product_id)


# ── Cycle 5: Ignore-link ─────────────────────────────────────────────────────

class IgnoreLinkTests(TestCase):
    """Branch 5: SupplierLink with product=None (ignore-link) → entry skipped, no embedding."""

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

        with patch(EMBED_PATH) as mock_embed:
            stats = run_matching(self.feed, rows)

        mock_embed.assert_not_called()
        self.assertEqual(stats.get('skipped', 0), 1)

        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='IGN-001')
        self.assertTrue(entry.skipped)
        self.assertIsNone(entry.product_id)

    def test_ignore_link_does_not_count_as_matched(self):
        """Ignored row must NOT increment the matched counter."""
        rows = [{'article': 'IGN-001', 'name': 'Что-то', 'price': '100'}]

        with patch(EMBED_PATH):
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

        with patch(EMBED_PATH) as mock_embed:
            stats = run_matching(self.feed, rows)

        mock_embed.assert_not_called()
        self.assertEqual(stats['matched'], 1)
        entry = SupplierFeedEntry.objects.get(feed=self.feed, supplier_sku='REG-001')
        self.assertEqual(entry.product_id, product.pk)
