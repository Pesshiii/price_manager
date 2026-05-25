"""API tests for MatchQueue endpoints — issue #106.

GET  /api/supplier-feed/feeds/{id}/queue/
POST /api/supplier-feed/feeds/{id}/queue/{entry_id}/resolve/
"""
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier_feed.models import SupplierFeed, SupplierFeedEntry, SupplierLink
from .fixtures import make_supplier, make_feed_mapping

FEED_LIST_URL = 'supplier_feed_api:supplierfeed-list'
QUEUE_URL = 'supplier_feed_api:supplierfeed-queue'
RESOLVE_URL = 'supplier_feed_api:supplierfeed-resolve'


def _make_product(name='Prod', sku='SKU-1'):
    from product.models import Product, Category, Brand
    brand = Brand.objects.get_or_create(name='Brand')[0]
    cat = Category.objects.get_or_create(name='Cat', defaults={'slug': 'cat'})[0]
    return Product.objects.create(name=name, sku=sku, brand=brand, category=cat)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='sf_queue_test_'),
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class QueueApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='queueuser', password='p')
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)

    def setUp(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse(FEED_LIST_URL),
            {'supplier': self.supplier.pk, 'feed_mapping': self.mapping.pk},
            content_type='application/json',
        )
        self.feed_id = resp.json()['id']
        self.feed = SupplierFeed.objects.get(pk=self.feed_id)

    def _make_entry(self, product=None, skipped=False, sku='SKU-X', data=None,
                    match_candidates=None):
        return SupplierFeedEntry.objects.create(
            feed=self.feed,
            supplier_sku=sku,
            product=product,
            skipped=skipped,
            data=data or {},
            match_candidates=match_candidates or [],
        )

    def _queue_url(self):
        return reverse(QUEUE_URL, args=[self.feed_id])

    def _resolve_url(self, entry_id):
        return reverse(RESOLVE_URL, args=[self.feed_id, entry_id])


# ── Cycle 1 (tracer): GET queue returns 200 with paginated shape ─────────────

class QueueListTracerTest(QueueApiBase):
    def test_queue_returns_200_with_paginated_shape(self):
        resp = self.client.get(self._queue_url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        self.assertIn('results', data)
        self.assertIn('count', data)
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['results'], [])


# ── Cycle 2: GET queue filters ─────────────────────────────────────────────

class QueueFilterTest(QueueApiBase):
    def test_queue_excludes_matched_entries(self):
        product = _make_product()
        self._make_entry(product=product, sku='matched-1')   # matched — must not appear
        self._make_entry(sku='queued-1')                     # queued  — must appear

        resp = self.client.get(self._queue_url())
        data = resp.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['supplier_sku'], 'queued-1')

    def test_queue_excludes_skipped_entries(self):
        self._make_entry(skipped=True, sku='skipped-1')      # skipped — must not appear
        self._make_entry(sku='queued-2')                     # queued  — must appear

        resp = self.client.get(self._queue_url())
        data = resp.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['supplier_sku'], 'queued-2')


# ── Cycle 3: GET queue response shape ─────────────────────────────────────

class QueueEntryShapeTest(QueueApiBase):
    def test_queue_entry_has_required_fields(self):
        candidates = [{'product_id': 99, 'score': 0.87, 'name': '候補'}]
        self._make_entry(
            sku='SHAPE-SKU',
            data={'col': 'val'},
            match_candidates=candidates,
        )
        resp = self.client.get(self._queue_url())
        entry = resp.json()['results'][0]
        self.assertIn('id', entry)
        self.assertEqual(entry['supplier_sku'], 'SHAPE-SKU')
        self.assertEqual(entry['data'], {'col': 'val'})
        self.assertEqual(entry['match_candidates'], candidates)


# ── Cycle 4: GET queue anonymous → 401 ─────────────────────────────────────

class QueueAuthTest(QueueApiBase):
    def test_anonymous_gets_401(self):
        self.client.logout()
        resp = self.client.get(self._queue_url())
        self.assertEqual(resp.status_code, 401)


# ── Cycle 5: GET queue pagination ──────────────────────────────────────────

class QueuePaginationTest(QueueApiBase):
    def test_queue_pagination_respects_page_size(self):
        for i in range(5):
            self._make_entry(sku=f'PAG-{i}')

        resp = self.client.get(self._queue_url(), {'page': 1, 'page_size': 2})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['count'], 5)
        self.assertEqual(len(data['results']), 2)

    def test_queue_pagination_page2(self):
        for i in range(5):
            self._make_entry(sku=f'PAG2-{i}')

        resp = self.client.get(self._queue_url(), {'page': 2, 'page_size': 2})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['results']), 2)

    def test_queue_pagination_next_and_previous_links(self):
        for i in range(5):
            self._make_entry(sku=f'LINK-{i}')

        resp = self.client.get(self._queue_url(), {'page': 1, 'page_size': 2})
        data = resp.json()
        self.assertIn('next', data)
        self.assertIn('previous', data)
        self.assertIsNotNone(data['next'])
        self.assertIsNone(data['previous'])


# ── Cycle 6: POST resolve with product_id sets entry.product ───────────────

class ResolveWithProductTest(QueueApiBase):
    def test_resolve_product_id_sets_entry_product(self):
        entry = self._make_entry(sku='RESOLVE-1')
        product = _make_product(name='P1', sku='P-001')

        resp = self.client.post(
            self._resolve_url(entry.pk),
            {'product_id': product.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        entry.refresh_from_db()
        self.assertEqual(entry.product_id, product.pk)


# ── Cycle 7: POST resolve with product_id creates SupplierLink ─────────────

class ResolveCreatesLinkTest(QueueApiBase):
    def test_resolve_creates_supplier_link(self):
        entry = self._make_entry(sku='LINK-SKU')
        product = _make_product(name='P2', sku='P-002')

        self.client.post(
            self._resolve_url(entry.pk),
            {'product_id': product.pk},
            content_type='application/json',
        )
        link = SupplierLink.objects.get(supplier=self.supplier, supplier_sku='LINK-SKU')
        self.assertEqual(link.product_id, product.pk)

    def test_resolve_updates_existing_supplier_link(self):
        product_old = _make_product(name='OldProd', sku='OLD-001')
        product_new = _make_product(name='NewProd', sku='NEW-001')
        SupplierLink.objects.create(
            supplier=self.supplier,
            supplier_sku='EXISTING-SKU',
            product=product_old,
        )
        entry = self._make_entry(sku='EXISTING-SKU')

        self.client.post(
            self._resolve_url(entry.pk),
            {'product_id': product_new.pk},
            content_type='application/json',
        )
        link = SupplierLink.objects.get(supplier=self.supplier, supplier_sku='EXISTING-SKU')
        self.assertEqual(link.product_id, product_new.pk)


# ── Cycle 8: POST resolve with skipped=true ─────────────────────────────────

class ResolveSkipTest(QueueApiBase):
    def test_resolve_skip_sets_skipped_flag(self):
        entry = self._make_entry(sku='SKIP-1')

        resp = self.client.post(
            self._resolve_url(entry.pk),
            {'skipped': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        entry.refresh_from_db()
        self.assertTrue(entry.skipped)
        self.assertIsNone(entry.product_id)


# ── Cycle 9: POST resolve empties queue → feed.status = 'done' ─────────────

class AutoDoneTransitionTest(QueueApiBase):
    def test_resolve_last_entry_transitions_feed_to_done(self):
        """When the last queued entry is resolved, feed.status must become 'done'."""
        entry = self._make_entry(sku='LAST-1')
        product = _make_product(name='P3', sku='P-003')

        self.client.post(
            self._resolve_url(entry.pk),
            {'product_id': product.pk},
            content_type='application/json',
        )
        self.feed.refresh_from_db()
        self.assertEqual(self.feed.status, 'done')

    def test_resolve_with_remaining_queue_does_not_transition(self):
        """With entries still queued, status must NOT change after one resolve."""
        entry1 = self._make_entry(sku='REMAIN-1')
        self._make_entry(sku='REMAIN-2')  # still queued
        product = _make_product(name='P4', sku='P-004')

        self.client.post(
            self._resolve_url(entry1.pk),
            {'product_id': product.pk},
            content_type='application/json',
        )
        self.feed.refresh_from_db()
        self.assertNotEqual(self.feed.status, 'done')


# ── Cycle 10: POST resolve entry from different feed → 404 ─────────────────

class ResolveOwnershipTest(QueueApiBase):
    def test_resolve_entry_from_other_feed_returns_404(self):
        other_feed = SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
        )
        other_entry = SupplierFeedEntry.objects.create(
            feed=other_feed,
            supplier_sku='OTHER-SKU',
        )
        product = _make_product(name='P5', sku='P-005')

        resp = self.client.post(
            self._resolve_url(other_entry.pk),   # entry belongs to other_feed
            {'product_id': product.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)


# ── Cycle 11: POST resolve double-resolve → 400 ─────────────────────────────

class ResolveDoubleResolveTest(QueueApiBase):
    def test_resolve_already_matched_entry_returns_400(self):
        product = _make_product(name='P6', sku='P-006')
        entry = self._make_entry(sku='DOUBLE-1', product=product)

        resp = self.client.post(
            self._resolve_url(entry.pk),
            {'product_id': product.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_resolve_already_skipped_entry_returns_400(self):
        entry = self._make_entry(sku='DOUBLE-2', skipped=True)

        resp = self.client.post(
            self._resolve_url(entry.pk),
            {'skipped': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


# ── Cycle 12: POST resolve anonymous → 401 ──────────────────────────────────

class ResolveAuthTest(QueueApiBase):
    def test_anonymous_resolve_returns_401(self):
        entry = self._make_entry(sku='AUTH-1')
        self.client.logout()

        resp = self.client.post(
            self._resolve_url(entry.pk),
            {'skipped': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)
