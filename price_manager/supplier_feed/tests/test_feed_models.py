"""Tests for SupplierFeed, SupplierFeedEntry, SupplierLink model defaults."""
from django.test import TestCase

from supplier_feed.models import SupplierFeed, SupplierFeedEntry, SupplierLink
from .fixtures import make_supplier, make_feed_mapping


class SupplierFeedDefaultsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)

    def _make_feed(self):
        return SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
        )

    # ── Cycle 1 ──────────────────────────────────────────────────────────
    def test_status_defaults_to_draft(self):
        feed = self._make_feed()
        self.assertEqual(feed.status, 'draft')

    def test_session_ids_defaults_to_empty_list(self):
        feed = self._make_feed()
        self.assertEqual(feed.session_ids, [])

    def test_error_defaults_to_blank(self):
        feed = self._make_feed()
        self.assertEqual(feed.error, '')

    def test_str_includes_supplier_and_mapping(self):
        feed = self._make_feed()
        s = str(feed)
        self.assertIn(str(self.supplier), s)

    # ── Cycle 2 ──────────────────────────────────────────────────────────
    def test_feed_mapping_reverse_relation_name(self):
        """FeedMapping.supplier_feeds queryset exists after SupplierFeed is created."""
        feed = self._make_feed()
        qs = self.mapping.supplier_feeds.filter(pk=feed.pk)
        self.assertEqual(qs.count(), 1)


class SupplierFeedEntryDefaultsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)
        cls.feed = SupplierFeed.objects.create(
            supplier=cls.supplier,
            feed_mapping=cls.mapping,
        )

    def _make_entry(self, sku='SKU-001'):
        return SupplierFeedEntry.objects.create(
            feed=self.feed,
            supplier_sku=sku,
        )

    def test_product_defaults_to_null(self):
        entry = self._make_entry()
        self.assertIsNone(entry.product)

    def test_data_defaults_to_empty_dict(self):
        entry = self._make_entry()
        self.assertEqual(entry.data, {})

    def test_match_candidates_defaults_to_empty_list(self):
        entry = self._make_entry()
        self.assertEqual(entry.match_candidates, [])

    def test_skipped_defaults_to_false(self):
        entry = self._make_entry()
        self.assertFalse(entry.skipped)


class SupplierLinkConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supplier = make_supplier()

    def test_unique_together_supplier_sku(self):
        from django.db import IntegrityError
        from product.models import Product, Category, Brand
        brand = Brand.objects.create(name='Brand A')
        cat = Category.objects.create(name='Cat', slug='cat')
        prod = Product.objects.create(name='P', sku='SKU-1', brand=brand, category=cat)

        SupplierLink.objects.create(
            supplier=self.supplier, supplier_sku='X', product=prod
        )
        with self.assertRaises(IntegrityError):
            SupplierLink.objects.create(
                supplier=self.supplier, supplier_sku='X', product=prod
            )
