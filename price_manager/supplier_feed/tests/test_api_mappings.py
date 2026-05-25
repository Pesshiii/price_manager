"""CRUD API tests for FeedMapping."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier_feed.models import FeedMapping
from .fixtures import make_currency, make_supplier, make_feed_mapping

MAPPING_LIST_URL = 'supplier_feed_api:feedmapping-list'
MAPPING_DETAIL_URL = 'supplier_feed_api:feedmapping-detail'


@override_settings(SECURE_SSL_REDIRECT=False)
class FeedMappingApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.supplier = make_supplier()

    def setUp(self):
        self.client.force_login(self.user)


# ── Cycle 2 ──────────────────────────────────────────────────────────────────

class AnonymousAccessTests(FeedMappingApiBase):
    def test_anonymous_gets_401(self):
        self.client.logout()
        resp = self.client.get(reverse(MAPPING_LIST_URL))
        self.assertEqual(resp.status_code, 401)


# ── Cycle 3 ──────────────────────────────────────────────────────────────────

class CreateFeedMappingTests(FeedMappingApiBase):
    def test_create_returns_201_and_persists(self):
        resp = self.client.post(
            reverse(MAPPING_LIST_URL),
            {
                'supplier': self.supplier.pk,
                'name': 'Прайс Рога',
                'supplier_sku_column': 'article',
                'identity_columns': ['article', 'name'],
                'variable_columns': ['price', 'stock'],
                'auto_match_threshold': 0.88,
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['name'], 'Прайс Рога')
        self.assertEqual(data['supplier_sku_column'], 'article')
        self.assertAlmostEqual(data['auto_match_threshold'], 0.88)
        self.assertEqual(FeedMapping.objects.count(), 1)

    def test_create_uses_default_threshold(self):
        resp = self.client.post(
            reverse(MAPPING_LIST_URL),
            {
                'supplier': self.supplier.pk,
                'name': 'Остатки',
                'supplier_sku_column': 'sku',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.assertAlmostEqual(resp.json()['auto_match_threshold'], 0.92)


# ── Cycle 4 ──────────────────────────────────────────────────────────────────

class ListFeedMappingTests(FeedMappingApiBase):
    def test_list_returns_all_mappings(self):
        make_feed_mapping(supplier=self.supplier, name='Прайс А')
        make_feed_mapping(supplier=self.supplier, name='Прайс Б')
        resp = self.client.get(reverse(MAPPING_LIST_URL))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # DefaultRouter without pagination returns a plain list
        self.assertEqual(len(body), 2)


# ── Cycle 5 ──────────────────────────────────────────────────────────────────

class DetailFeedMappingTests(FeedMappingApiBase):
    def test_retrieve_returns_mapping(self):
        mapping = make_feed_mapping(supplier=self.supplier, name='Прайс')
        resp = self.client.get(reverse(MAPPING_DETAIL_URL, args=[mapping.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Прайс')


# ── Cycle 6 ──────────────────────────────────────────────────────────────────

class UpdateFeedMappingTests(FeedMappingApiBase):
    def test_patch_updates_field(self):
        mapping = make_feed_mapping(supplier=self.supplier, name='Прайс')
        resp = self.client.patch(
            reverse(MAPPING_DETAIL_URL, args=[mapping.pk]),
            {'auto_match_threshold': 0.85},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertAlmostEqual(resp.json()['auto_match_threshold'], 0.85)
        mapping.refresh_from_db()
        self.assertAlmostEqual(mapping.auto_match_threshold, 0.85)


# ── Cycle 7 ──────────────────────────────────────────────────────────────────

class DeleteFeedMappingTests(FeedMappingApiBase):
    def test_delete_returns_204_and_removes_object(self):
        mapping = make_feed_mapping(supplier=self.supplier, name='Прайс')
        resp = self.client.delete(reverse(MAPPING_DETAIL_URL, args=[mapping.pk]))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(FeedMapping.objects.filter(pk=mapping.pk).exists())


# ── Cycle 8 ──────────────────────────────────────────────────────────────────

class DeleteProtectionTests(FeedMappingApiBase):
    """DELETE is blocked with 409 when the mapping has associated SupplierFeed sessions."""

    def test_delete_blocked_when_supplier_feed_exists(self):
        from supplier_feed.models import SupplierFeed

        mapping = make_feed_mapping(supplier=self.supplier, name='Прайс')
        # Create a real SupplierFeed referencing this mapping.
        SupplierFeed.objects.create(supplier=self.supplier, feed_mapping=mapping)

        resp = self.client.delete(reverse(MAPPING_DETAIL_URL, args=[mapping.pk]))

        self.assertEqual(resp.status_code, 409)
        self.assertTrue(FeedMapping.objects.filter(pk=mapping.pk).exists())
