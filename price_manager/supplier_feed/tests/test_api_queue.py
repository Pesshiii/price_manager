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
CREATE_PRODUCT_URL = 'supplier_feed_api:supplierfeed-create-product'
IGNORE_URL = 'supplier_feed_api:supplierfeed-ignore'
BULK_CREATE_URL = 'supplier_feed_api:supplierfeed-bulk-create-products'


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
                    match_candidates=None, best_score=None):
        return SupplierFeedEntry.objects.create(
            feed=self.feed,
            supplier_sku=sku,
            product=product,
            skipped=skipped,
            data=data or {},
            match_candidates=match_candidates or [],
            best_score=best_score,
        )

    def _queue_url(self):
        return reverse(QUEUE_URL, args=[self.feed_id])

    def _resolve_url(self, entry_id):
        return reverse(RESOLVE_URL, args=[self.feed_id, entry_id])

    def _create_product_url(self, entry_id):
        return reverse(CREATE_PRODUCT_URL, args=[self.feed_id, entry_id])

    def _ignore_url(self, entry_id):
        return reverse(IGNORE_URL, args=[self.feed_id, entry_id])

    def _bulk_create_url(self):
        return reverse(BULK_CREATE_URL, args=[self.feed_id])


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
        candidates = [{'product_id': 99, 'score': 0.87, 'name': 'Насос', 'sku': 'NB-100',
                       'category': 'Насосы', 'brand': 'Grundfos'}]
        self._make_entry(
            sku='SHAPE-SKU',
            data={'col': 'val'},
            match_candidates=candidates,
            best_score=0.87,
        )
        resp = self.client.get(self._queue_url())
        entry = resp.json()['results'][0]
        self.assertIn('id', entry)
        self.assertEqual(entry['supplier_sku'], 'SHAPE-SKU')
        self.assertEqual(entry['data'], {'col': 'val'})
        self.assertEqual(entry['match_candidates'], candidates)
        self.assertAlmostEqual(entry['best_score'], 0.87)

    def test_entry_with_no_candidates_has_null_best_score(self):
        self._make_entry(sku='NULL-SCORE', best_score=None)
        resp = self.client.get(self._queue_url())
        entry = resp.json()['results'][0]
        self.assertIsNone(entry['best_score'])


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


# ── Cycle 13: POST create-product happy path ──────────────────────────────────

class CreateProductHappyPathTest(QueueApiBase):
    def test_creates_product_link_and_resolves_entry(self):
        """create-product: Product created with draft status, SupplierLink set, entry resolved."""
        entry = self._make_entry(sku='CREATE-1')

        resp = self.client.post(
            self._create_product_url(entry.pk),
            {'sku': 'NEW-SKU-001', 'name': 'Новый Товар'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])

        from product.models import Product
        product = Product.objects.get(sku='NEW-SKU-001')
        self.assertEqual(product.name, 'Новый Товар')
        self.assertEqual(product.status, 'draft')

        entry.refresh_from_db()
        self.assertEqual(entry.product_id, product.pk)

        link = SupplierLink.objects.get(supplier=self.supplier, supplier_sku='CREATE-1')
        self.assertEqual(link.product_id, product.pk)

    def test_transitions_feed_to_done_when_last_entry(self):
        entry = self._make_entry(sku='CREATE-LAST')

        self.client.post(
            self._create_product_url(entry.pk),
            {'sku': 'LAST-SKU-001', 'name': 'Последний'},
            content_type='application/json',
        )
        self.feed.refresh_from_db()
        self.assertEqual(self.feed.status, 'done')


# ── Cycle 14: POST create-product validation ──────────────────────────────────

class CreateProductValidationTest(QueueApiBase):
    def test_duplicate_sku_returns_400(self):
        _make_product(sku='EXISTING-SKU-X')
        entry = self._make_entry(sku='CREATE-DUP')

        resp = self.client.post(
            self._create_product_url(entry.pk),
            {'sku': 'EXISTING-SKU-X', 'name': 'Попытка дублирования'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_on_already_resolved_entry_returns_400(self):
        product = _make_product(name='Already', sku='ALREADY-001')
        entry = self._make_entry(sku='CREATE-RESOLVED', product=product)

        resp = self.client.post(
            self._create_product_url(entry.pk),
            {'sku': 'NEW-002', 'name': 'Что-то'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


# ── Cycle 15: POST ignore happy path ─────────────────────────────────────────

class IgnoreHappyPathTest(QueueApiBase):
    def test_creates_ignore_link_and_skips_entry(self):
        """ignore: ignore-link (product=None) created, entry.skipped=True."""
        entry = self._make_entry(sku='IGN-1')

        resp = self.client.post(
            self._ignore_url(entry.pk),
            {},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        entry.refresh_from_db()
        self.assertTrue(entry.skipped)

        link = SupplierLink.objects.get(supplier=self.supplier, supplier_sku='IGN-1')
        self.assertIsNone(link.product_id)

    def test_transitions_feed_to_done_when_last_entry(self):
        entry = self._make_entry(sku='IGN-LAST')

        self.client.post(self._ignore_url(entry.pk), {}, content_type='application/json')
        self.feed.refresh_from_db()
        self.assertEqual(self.feed.status, 'done')


# ── Cycle 16: POST ignore validation ─────────────────────────────────────────

class IgnoreValidationTest(QueueApiBase):
    def test_on_already_resolved_entry_returns_400(self):
        product = _make_product(name='Resolved', sku='RES-IGN-001')
        entry = self._make_entry(sku='IGN-RESOLVED', product=product)

        resp = self.client.post(
            self._ignore_url(entry.pk),
            {},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_on_already_skipped_entry_returns_400(self):
        entry = self._make_entry(sku='IGN-SKIP', skipped=True)

        resp = self.client.post(
            self._ignore_url(entry.pk),
            {},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


# ── Cycle 17: Queue sort order ────────────────────────────────────────────────

class QueueSortOrderTest(QueueApiBase):
    """Queue must be sorted: NULL best_score first, then DESC by score."""

    def test_null_score_entry_appears_before_scored_entries(self):
        """Entry with best_score=None (anomaly) must appear before scored entries."""
        self._make_entry(sku='HIGH', best_score=0.85)
        self._make_entry(sku='NULL', best_score=None)
        self._make_entry(sku='LOW', best_score=0.30)

        resp = self.client.get(self._queue_url())
        skus = [e['supplier_sku'] for e in resp.json()['results']]
        self.assertEqual(skus[0], 'NULL')

    def test_higher_score_appears_before_lower_score(self):
        """Among scored entries, higher best_score comes first."""
        self._make_entry(sku='LOW', best_score=0.30)
        self._make_entry(sku='HIGH', best_score=0.85)

        resp = self.client.get(self._queue_url())
        skus = [e['supplier_sku'] for e in resp.json()['results']]
        self.assertEqual(skus, ['HIGH', 'LOW'])

    def test_full_sort_order(self):
        """NULL first, then descending score."""
        self._make_entry(sku='MID', best_score=0.60)
        self._make_entry(sku='NULL', best_score=None)
        self._make_entry(sku='HIGH', best_score=0.85)
        self._make_entry(sku='LOW', best_score=0.20)

        resp = self.client.get(self._queue_url())
        skus = [e['supplier_sku'] for e in resp.json()['results']]
        self.assertEqual(skus, ['NULL', 'HIGH', 'MID', 'LOW'])


# ── Cycle 18: POST bulk-create-products happy path ───────────────────────────

class BulkCreateProductsHappyPathTest(QueueApiBase):
    def test_creates_products_for_all_queued_entries(self):
        """All queued entries get Product(draft) + SupplierLink created."""
        self._make_entry(sku='BULK-1', data={'name': 'Товар 1', 'price': '100'})
        self._make_entry(sku='BULK-2', data={'name': 'Товар 2', 'price': '200'})

        resp = self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['created'], 2)
        self.assertEqual(data['failed'], 0)
        self.assertEqual(data['errors'], [])

        from product.models import Product
        self.assertTrue(Product.objects.filter(name='Товар 1').exists())
        self.assertTrue(Product.objects.filter(name='Товар 2').exists())

    def test_creates_supplier_links_for_each_entry(self):
        self._make_entry(sku='BLINK-1', data={'name': 'Насос'})

        self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        link = SupplierLink.objects.get(supplier=self.supplier, supplier_sku='BLINK-1')
        self.assertIsNotNone(link.product_id)

    def test_entry_product_is_set_after_bulk_create(self):
        entry = self._make_entry(sku='BPROD-1', data={'name': 'Дрель'})

        self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        entry.refresh_from_db()
        self.assertIsNotNone(entry.product_id)

    def test_transitions_feed_to_done_when_queue_empties(self):
        self._make_entry(sku='BDONE-1', data={'name': 'Товар'})

        self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        self.feed.refresh_from_db()
        self.assertEqual(self.feed.status, 'done')

    def test_sku_from_product_sku_column_when_configured(self):
        """SKU is taken from product_sku_column if configured in FeedMapping."""
        self.mapping.product_sku_column = 'internal_sku'
        self.mapping.save(update_fields=['product_sku_column'])
        self._make_entry(sku='BSKU-1', data={'name': 'Фен', 'internal_sku': 'INT-001'})

        self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        from product.models import Product
        self.assertTrue(Product.objects.filter(sku='INT-001').exists())

    def test_sku_falls_back_to_supplier_sku_when_no_column(self):
        """Without product_sku_column, supplier_sku is used as product SKU."""
        self._make_entry(sku='BFALLBACK-1', data={'name': 'Шуруп'})

        self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        from product.models import Product
        self.assertTrue(Product.objects.filter(sku='BFALLBACK-1').exists())


# ── Cycle 19: POST bulk-create-products skip-and-continue ────────────────────

class BulkCreateProductsSkipTest(QueueApiBase):
    def test_sku_conflict_is_skipped_and_rest_created(self):
        """Conflicting SKU entry is skipped; other entries are still created."""
        from product.models import Product, Brand, Category
        brand = Brand.objects.get_or_create(name='B')[0]
        cat = Category.objects.get_or_create(name='C', defaults={'slug': 'c'})[0]
        Product.objects.create(sku='CONFLICT-SKU', name='Существующий', brand=brand, category=cat)

        self._make_entry(sku='CONFLICT-SKU', data={'name': 'Дубль'})
        self._make_entry(sku='OK-SKU', data={'name': 'Новый'})

        resp = self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        data = resp.json()
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['failed'], 1)
        self.assertEqual(len(data['errors']), 1)
        self.assertTrue(Product.objects.filter(sku='OK-SKU').exists())

    def test_missing_name_column_is_skipped(self):
        """Entry without the specified name column is skipped."""
        self._make_entry(sku='NO-NAME', data={'price': '100'})

        resp = self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        data = resp.json()
        self.assertEqual(data['created'], 0)
        self.assertEqual(data['failed'], 1)
        self.assertEqual(len(data['errors']), 1)
        self.assertIn('name', data['errors'][0]['reason'])

    def test_skipped_entry_remains_in_queue(self):
        """Failed entry stays in queue (product=None, skipped=False)."""
        from product.models import Product, Brand, Category
        brand = Brand.objects.get_or_create(name='B2')[0]
        cat = Category.objects.get_or_create(name='C2', defaults={'slug': 'c2'})[0]
        Product.objects.create(sku='DUP-QUEUE', name='Dup', brand=brand, category=cat)

        entry = self._make_entry(sku='DUP-QUEUE', data={'name': 'Дубль'})

        self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        entry.refresh_from_db()
        self.assertIsNone(entry.product_id)
        self.assertFalse(entry.skipped)


# ── Cycle 20: POST bulk-create-products validation ───────────────────────────

class BulkCreateProductsValidationTest(QueueApiBase):
    def test_missing_name_column_param_returns_400(self):
        resp = self.client.post(
            self._bulk_create_url(),
            {},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_empty_queue_returns_zero_counts(self):
        """With no queued entries, returns {created:0, failed:0, errors:[]}."""
        resp = self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['created'], 0)
        self.assertEqual(data['failed'], 0)

    def test_anonymous_returns_401(self):
        self.client.logout()
        resp = self.client.post(
            self._bulk_create_url(),
            {'name_column': 'name'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)
