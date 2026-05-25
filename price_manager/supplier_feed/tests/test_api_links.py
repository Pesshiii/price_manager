"""API tests for SupplierLink — issue #107.

Cycles:
  1  (tracer) GET /links/ returns 200 with nested supplier + product objects
  2  Filter by ?supplier=<id>
  3  Filter by ?supplier_sku=<partial> (icontains)
  4  Filter by ?product=<id>
  5  DELETE returns 204 and removes the record
  6  DELETE does not affect related SupplierFeedEntry records
  7  PATCH {product_id} reassigns product, returns 200 with updated data
  8  PATCH is idempotent (same product_id → 200, no change)
  9  PATCH with nonexistent product_id → 400
  10 Anonymous → 401 on all endpoints
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier_feed.models import SupplierFeedEntry, SupplierLink, SupplierFeed
from .fixtures import make_supplier, make_feed_mapping, make_product

LINK_LIST_URL = 'supplier_feed_api:supplierlink-list'
LINK_DETAIL_URL = 'supplier_feed_api:supplierlink-detail'


@override_settings(SECURE_SSL_REDIRECT=False)
class SupplierLinkApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='linkuser', password='p')
        cls.supplier = make_supplier(name='Поставщик А')
        cls.product = make_product(sku='SKU-A', name='Товар А')

    def setUp(self):
        self.client.force_login(self.user)

    def _make_link(self, supplier=None, sku='ART-001', product=None):
        return SupplierLink.objects.create(
            supplier=supplier or self.supplier,
            supplier_sku=sku,
            product=product or self.product,
        )


# ── Cycle 1 (tracer) ─────────────────────────────────────────────────────────

class ListLinksTracerTest(SupplierLinkApiBase):
    def test_list_returns_200_with_nested_supplier_and_product(self):
        """GET /links/ returns 200; each item has nested supplier {id,name}
        and product {id,name,sku}."""
        self._make_link()

        resp = self.client.get(reverse(LINK_LIST_URL))

        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        self.assertEqual(len(data), 1)

        item = data[0]
        self.assertIn('id', item)
        self.assertIn('supplier_sku', item)

        # Nested supplier object
        supplier_obj = item['supplier']
        self.assertIsInstance(supplier_obj, dict)
        self.assertEqual(supplier_obj['id'], self.supplier.pk)
        self.assertEqual(supplier_obj['name'], self.supplier.name)

        # Nested product object
        product_obj = item['product']
        self.assertIsInstance(product_obj, dict)
        self.assertEqual(product_obj['id'], self.product.pk)
        self.assertEqual(product_obj['name'], self.product.name)
        self.assertEqual(product_obj['sku'], self.product.sku)


# ── Cycles 2-4: filtering ─────────────────────────────────────────────────────

class FilterLinksTests(SupplierLinkApiBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.supplier_b = make_supplier(name='Поставщик Б')
        cls.product_b = make_product(sku='SKU-B', name='Товар Б')

    def setUp(self):
        super().setUp()
        # Fresh links each test (uses transactions)
        self.link_a = self._make_link(supplier=self.supplier, sku='ART-ALPHA')
        self.link_b = SupplierLink.objects.create(
            supplier=self.supplier_b,
            supplier_sku='ART-BETA',
            product=self.product_b,
        )

    # ── Cycle 2 ──────────────────────────────────────────────────────────────

    def test_filter_by_supplier_returns_only_that_supplier(self):
        resp = self.client.get(reverse(LINK_LIST_URL), {'supplier': self.supplier.pk})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['supplier']['id'], self.supplier.pk)

    # ── Cycle 3 ──────────────────────────────────────────────────────────────

    def test_filter_by_supplier_sku_icontains(self):
        resp = self.client.get(reverse(LINK_LIST_URL), {'supplier_sku': 'ALPHA'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['supplier_sku'], 'ART-ALPHA')

    def test_filter_by_supplier_sku_case_insensitive(self):
        resp = self.client.get(reverse(LINK_LIST_URL), {'supplier_sku': 'alpha'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    # ── Cycle 4 ──────────────────────────────────────────────────────────────

    def test_filter_by_product_returns_only_that_product(self):
        resp = self.client.get(reverse(LINK_LIST_URL), {'product': self.product_b.pk})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['product']['id'], self.product_b.pk)


# ── Cycles 5-6: DELETE ────────────────────────────────────────────────────────

class DeleteLinkTests(SupplierLinkApiBase):
    def setUp(self):
        super().setUp()
        self.link = self._make_link()

    # ── Cycle 5 ──────────────────────────────────────────────────────────────

    def test_delete_returns_204_and_removes_record(self):
        resp = self.client.delete(reverse(LINK_DETAIL_URL, args=[self.link.pk]))
        self.assertEqual(resp.status_code, 204, resp.content[:300])
        self.assertFalse(SupplierLink.objects.filter(pk=self.link.pk).exists())

    # ── Cycle 6 ──────────────────────────────────────────────────────────────

    def test_delete_does_not_affect_feed_entries(self):
        """Deleting a SupplierLink must not cascade-delete any SupplierFeedEntry rows."""
        mapping = make_feed_mapping(supplier=self.supplier)
        feed = SupplierFeed.objects.create(supplier=self.supplier, feed_mapping=mapping)
        entry = SupplierFeedEntry.objects.create(
            feed=feed,
            supplier_sku=self.link.supplier_sku,
            product=self.product,
        )

        self.client.delete(reverse(LINK_DETAIL_URL, args=[self.link.pk]))

        # Entry survived
        self.assertTrue(SupplierFeedEntry.objects.filter(pk=entry.pk).exists())


# ── Cycles 7-9: PATCH ────────────────────────────────────────────────────────

class PatchLinkTests(SupplierLinkApiBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.product_new = make_product(sku='SKU-NEW', name='Новый Товар', brand_name='Новый Бренд', category_name='Новая Кат')

    def setUp(self):
        super().setUp()
        self.link = self._make_link(product=self.product)

    # ── Cycle 7 ──────────────────────────────────────────────────────────────

    def test_patch_reassigns_product_returns_200_with_updated_data(self):
        resp = self.client.patch(
            reverse(LINK_DETAIL_URL, args=[self.link.pk]),
            {'product_id': self.product_new.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        data = resp.json()
        self.assertEqual(data['product']['id'], self.product_new.pk)
        self.assertEqual(data['product']['sku'], self.product_new.sku)

        # Persisted
        self.link.refresh_from_db()
        self.assertEqual(self.link.product_id, self.product_new.pk)

    # ── Cycle 8 ──────────────────────────────────────────────────────────────

    def test_patch_is_idempotent_when_product_already_same(self):
        resp = self.client.patch(
            reverse(LINK_DETAIL_URL, args=[self.link.pk]),
            {'product_id': self.product.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['product']['id'], self.product.pk)

    # ── Cycle 9 ──────────────────────────────────────────────────────────────

    def test_patch_with_nonexistent_product_id_returns_400(self):
        resp = self.client.patch(
            reverse(LINK_DETAIL_URL, args=[self.link.pk]),
            {'product_id': 9999999},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


# ── Cycle 10: authentication ──────────────────────────────────────────────────

class AuthTests(SupplierLinkApiBase):
    def setUp(self):
        # Do NOT log in
        pass

    def test_list_anonymous_returns_401(self):
        resp = self.client.get(reverse(LINK_LIST_URL))
        self.assertEqual(resp.status_code, 401)

    def test_delete_anonymous_returns_401(self):
        link = self._make_link()
        resp = self.client.delete(reverse(LINK_DETAIL_URL, args=[link.pk]))
        self.assertEqual(resp.status_code, 401)

    def test_patch_anonymous_returns_401(self):
        link = self._make_link()
        resp = self.client.patch(
            reverse(LINK_DETAIL_URL, args=[link.pk]),
            {'product_id': self.product.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)
