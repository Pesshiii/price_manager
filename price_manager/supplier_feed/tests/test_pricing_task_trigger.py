"""Tests that _try_close_feed dispatches apply_feed_pricing via Celery on commit."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier_feed.models import STATUS_DONE, SupplierFeed, SupplierFeedEntry
from .fixtures import make_feed_mapping, make_product, make_supplier

RESOLVE_URL = 'supplier_feed_api:supplierfeed-resolve'


@override_settings(SECURE_SSL_REDIRECT=False)
class PricingTaskTriggerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='trigger_u', password='p')
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)

    def setUp(self):
        self.client.force_login(self.user)

    def _make_feed_with_one_queued(self):
        product = make_product(sku='TR-001')
        feed = SupplierFeed.objects.create(
            supplier=self.supplier, feed_mapping=self.mapping, status='partial'
        )
        matched = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='M', product=product, data={}
        )
        queued = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='Q', product=None, data={}
        )
        return feed, product, matched, queued

    @patch('pricing.tasks.apply_feed_pricing.delay')
    def test_apply_feed_pricing_called_on_done(self, mock_delay):
        feed, product, _matched, queued = self._make_feed_with_one_queued()

        url = reverse(RESOLVE_URL, args=[feed.pk, queued.pk])
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, {'product_id': product.pk}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_DONE)
        mock_delay.assert_called_once_with(feed.pk)

    @patch('pricing.tasks.apply_feed_pricing.delay')
    def test_apply_feed_pricing_not_called_when_queue_not_empty(self, mock_delay):
        product = make_product(sku='TR-002')
        feed = SupplierFeed.objects.create(
            supplier=self.supplier, feed_mapping=self.mapping, status='partial'
        )
        queued1 = SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='Q1', product=None, data={}
        )
        SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='Q2', product=None, data={}
        )

        url = reverse(RESOLVE_URL, args=[feed.pk, queued1.pk])
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(url, {'product_id': product.pk}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        feed.refresh_from_db()
        self.assertNotEqual(feed.status, STATUS_DONE)
        mock_delay.assert_not_called()
