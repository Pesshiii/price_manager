"""API tests for SupplierFeed sessions — lifecycle in 'draft' state."""
import io
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier_feed.models import SupplierFeed, SupplierFeedEntry
from .fixtures import make_supplier, make_feed_mapping

FEED_LIST_URL = 'supplier_feed_api:supplierfeed-list'
FEED_DETAIL_URL = 'supplier_feed_api:supplierfeed-detail'
FEED_UPLOAD_URL = 'supplier_feed_api:supplierfeed-upload'
FEED_DELETE_FILE_URL = 'supplier_feed_api:supplierfeed-delete-file'
FEED_PROCESS_URL = 'supplier_feed_api:supplierfeed-process'


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='sf_feed_test_'),
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class SupplierFeedApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='feeduser', password='p')
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)

    def setUp(self):
        self.client.force_login(self.user)

    def _create_feed(self, supplier=None, mapping=None):
        return self.client.post(
            reverse(FEED_LIST_URL),
            {
                'supplier': (supplier or self.supplier).pk,
                'feed_mapping': (mapping or self.mapping).pk,
            },
            content_type='application/json',
        )


# ── Cycle 3 ───────────────────────────────────────────────────────────────────

class CreateFeedTests(SupplierFeedApiBase):
    def test_create_returns_201_with_draft_status(self):
        resp = self._create_feed()
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['status'], 'draft')
        self.assertEqual(data['session_ids'], [])
        self.assertEqual(SupplierFeed.objects.count(), 1)

    def test_anonymous_gets_401(self):
        self.client.logout()
        resp = self._create_feed()
        self.assertEqual(resp.status_code, 401)


# ── Cycle 4 ───────────────────────────────────────────────────────────────────

class ListFeedFilterTests(SupplierFeedApiBase):
    def test_list_returns_feeds(self):
        self._create_feed()
        resp = self.client.get(reverse(FEED_LIST_URL))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_filter_by_supplier_excludes_other(self):
        from .fixtures import make_supplier as _ms
        other_supplier = _ms(name='Другой')
        other_mapping = make_feed_mapping(supplier=other_supplier, name='Маппинг Другой')
        self._create_feed()
        self._create_feed(supplier=other_supplier, mapping=other_mapping)

        resp = self.client.get(
            reverse(FEED_LIST_URL),
            {'supplier': self.supplier.pk},
        )
        self.assertEqual(resp.status_code, 200)
        results = resp.json()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['supplier'], self.supplier.pk)

    def test_filter_by_status(self):
        self._create_feed()
        resp_draft = self.client.get(reverse(FEED_LIST_URL), {'status': 'draft'})
        self.assertEqual(len(resp_draft.json()), 1)
        resp_done = self.client.get(reverse(FEED_LIST_URL), {'status': 'done'})
        self.assertEqual(len(resp_done.json()), 0)


# ── Cycle 5 ───────────────────────────────────────────────────────────────────

class FeedDetailStatsTests(SupplierFeedApiBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        resp = self._create_feed()
        self.feed_id = resp.json()['id']
        self.feed = SupplierFeed.objects.get(pk=self.feed_id)

    def _make_entry(self, product=None, skipped=False, sku='SKU-X'):
        return SupplierFeedEntry.objects.create(
            feed=self.feed,
            supplier_sku=sku,
            product=product,
            skipped=skipped,
        )

    def test_detail_returns_stats_all_zeros_when_empty(self):
        resp = self.client.get(reverse(FEED_DETAIL_URL, args=[self.feed_id]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['matched'], 0)
        self.assertEqual(data['queued'], 0)
        self.assertEqual(data['skipped'], 0)

    def test_detail_stats_count_correctly(self):
        from product.models import Product, Category, Brand
        brand = Brand.objects.create(name='B2')
        cat = Category.objects.create(name='Cat2', slug='cat2')
        prod = Product.objects.create(name='Prod2', sku='SKU-PROD2', brand=brand, category=cat)

        self._make_entry(sku='sku-1')                       # queued
        self._make_entry(product=prod, sku='sku-2')         # matched
        self._make_entry(skipped=True, sku='sku-3')         # skipped

        resp = self.client.get(reverse(FEED_DETAIL_URL, args=[self.feed_id]))
        data = resp.json()
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['matched'], 1)
        self.assertEqual(data['queued'], 1)
        self.assertEqual(data['skipped'], 1)


# ── Cycle 6 ───────────────────────────────────────────────────────────────────

class UploadFileTests(SupplierFeedApiBase):
    def setUp(self):
        super().setUp()
        resp = self._create_feed()
        self.feed_id = resp.json()['id']

    def _upload(self, content=b'col1,col2\nval1,val2\n', filename='price.csv'):
        return self.client.post(
            reverse(FEED_UPLOAD_URL, args=[self.feed_id]),
            {'file': io.BytesIO(content)},
            format='multipart',
        )

    def test_upload_returns_201_with_session_metadata(self):
        resp = self._upload()
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        data = resp.json()
        self.assertIn('session_id', data)
        self.assertIn('filename', data)
        self.assertIn('size', data)

    def test_upload_appends_session_id_to_feed(self):
        self._upload()
        feed = SupplierFeed.objects.get(pk=self.feed_id)
        self.assertEqual(len(feed.session_ids), 1)

    def test_upload_multiple_files(self):
        self._upload(filename='file1.csv')
        self._upload(filename='file2.csv')
        feed = SupplierFeed.objects.get(pk=self.feed_id)
        self.assertEqual(len(feed.session_ids), 2)

    def test_upload_without_file_returns_400(self):
        resp = self.client.post(
            reverse(FEED_UPLOAD_URL, args=[self.feed_id]),
            {},
            format='multipart',
        )
        self.assertEqual(resp.status_code, 400)


# ── Cycle 7-8 ─────────────────────────────────────────────────────────────────

class DeleteFileTests(SupplierFeedApiBase):
    def setUp(self):
        super().setUp()
        resp = self._create_feed()
        self.feed_id = resp.json()['id']
        # Upload one file to get a session_id
        up = self.client.post(
            reverse(FEED_UPLOAD_URL, args=[self.feed_id]),
            {'file': io.BytesIO(b'a,b\n1,2\n')},
            format='multipart',
        )
        self.session_id = up.json()['session_id']

    def test_delete_file_from_draft_returns_204(self):
        resp = self.client.delete(
            reverse(FEED_DELETE_FILE_URL, args=[self.feed_id, self.session_id]),
        )
        self.assertEqual(resp.status_code, 204)
        feed = SupplierFeed.objects.get(pk=self.feed_id)
        self.assertNotIn(self.session_id, feed.session_ids)

    def test_delete_file_from_non_draft_returns_403(self):
        SupplierFeed.objects.filter(pk=self.feed_id).update(status='processing')
        resp = self.client.delete(
            reverse(FEED_DELETE_FILE_URL, args=[self.feed_id, self.session_id]),
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_unknown_session_id_returns_404(self):
        unknown = 'a' * 32
        resp = self.client.delete(
            reverse(FEED_DELETE_FILE_URL, args=[self.feed_id, unknown]),
        )
        self.assertEqual(resp.status_code, 404)


# ── Cycles 9-10: /process/ endpoint ──────────────────────────────────────────

_TASK_DELAY = 'supplier_feed.api.views.run_feed_matching_task.delay'


class ProcessEndpointTests(SupplierFeedApiBase):
    """POST /feeds/{id}/process/ — trigger matching task from draft status."""

    def setUp(self):
        super().setUp()
        resp = self._create_feed()
        self.feed_id = resp.json()['id']

    # ── Cycle 9 (tracer) ──────────────────────────────────────────────────────

    def test_process_draft_returns_202_with_processing_status(self):
        """Draft feed: /process/ sets status to 'processing', queues task, returns 202."""
        with patch(_TASK_DELAY) as mock_delay:
            resp = self.client.post(
                reverse(FEED_PROCESS_URL, args=[self.feed_id]),
            )

        self.assertEqual(resp.status_code, 202, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['status'], 'processing')

        # Task was queued with the feed's primary key
        mock_delay.assert_called_once_with(self.feed_id)

        # Persisted in DB
        feed = SupplierFeed.objects.get(pk=self.feed_id)
        self.assertEqual(feed.status, 'processing')

    # ── Cycle 10 ──────────────────────────────────────────────────────────────

    def test_process_non_draft_returns_400(self):
        """Feed not in draft state → 400 Bad Request."""
        SupplierFeed.objects.filter(pk=self.feed_id).update(status='processing')

        resp = self.client.post(
            reverse(FEED_PROCESS_URL, args=[self.feed_id]),
        )
        self.assertEqual(resp.status_code, 400)

    def test_process_anonymous_returns_401(self):
        """Unauthenticated request → 401."""
        self.client.logout()
        resp = self.client.post(
            reverse(FEED_PROCESS_URL, args=[self.feed_id]),
        )
        self.assertEqual(resp.status_code, 401)
