"""Tests for supplier_feed models — defaults and constraints."""
from django.test import TestCase

from supplier_feed.models import FeedMapping
from .fixtures import make_feed_mapping, make_supplier


class FeedMappingDefaultsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supplier = make_supplier()

    def test_auto_match_threshold_default(self):
        mapping = make_feed_mapping(supplier=self.supplier)
        self.assertAlmostEqual(mapping.auto_match_threshold, 0.92)

    def test_identity_columns_default_empty_list(self):
        mapping = make_feed_mapping(supplier=self.supplier)
        self.assertEqual(mapping.identity_columns, [])

    def test_variable_columns_default_empty_list(self):
        mapping = make_feed_mapping(supplier=self.supplier)
        self.assertEqual(mapping.variable_columns, [])
