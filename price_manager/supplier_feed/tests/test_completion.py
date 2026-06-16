"""Unit tests for the unified `complete_feed` transition.

`complete_feed` is the single owner of the `partial → done` transition shared
by the matching task and the MatchQueue viewset actions. These tests pin its
contract directly; the two callers are covered in test_tasks.py and
test_pricing_task_trigger.py.
"""
from unittest.mock import patch

from django.test import TestCase

from supplier_feed.completion import complete_feed, queue_is_empty
from supplier_feed.models import (
    STATUS_DONE,
    STATUS_PARTIAL,
    SupplierFeed,
    SupplierFeedEntry,
)
from .fixtures import make_feed_mapping, make_product, make_supplier

_DELAY_PATH = 'pricing.tasks.apply_feed_pricing.delay'


class CompleteFeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supplier = make_supplier(name='Completion Supplier')
        cls.mapping = make_feed_mapping(supplier=cls.supplier)

    def _feed(self, status=STATUS_PARTIAL):
        return SupplierFeed.objects.create(
            supplier=self.supplier, feed_mapping=self.mapping, status=status
        )

    @patch(_DELAY_PATH)
    def test_transitions_to_done_and_triggers_pricing_when_queue_empty(self, mock_delay):
        feed = self._feed()
        product = make_product(sku='C-1')
        SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='A', product=product, data={}
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = complete_feed(feed)

        self.assertTrue(result)
        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_DONE)
        self.assertEqual(feed.error, '')
        mock_delay.assert_called_once_with(feed.pk)

    @patch(_DELAY_PATH)
    def test_clears_stale_error_on_completion(self, mock_delay):
        feed = self._feed()
        feed.error = 'предыдущая ошибка'
        feed.save(update_fields=['error'])

        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(complete_feed(feed))

        feed.refresh_from_db()
        self.assertEqual(feed.error, '')

    @patch(_DELAY_PATH)
    def test_no_transition_when_queue_not_empty(self, mock_delay):
        feed = self._feed()
        SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='Q', product=None, skipped=False, data={}
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = complete_feed(feed)

        self.assertFalse(result)
        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_PARTIAL)
        mock_delay.assert_not_called()

    @patch(_DELAY_PATH)
    def test_skipped_entries_do_not_block_completion(self, mock_delay):
        feed = self._feed()
        SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='S', product=None, skipped=True, data={}
        )

        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(complete_feed(feed))

        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_DONE)
        mock_delay.assert_called_once_with(feed.pk)

    @patch(_DELAY_PATH)
    def test_idempotent_when_already_done(self, mock_delay):
        feed = self._feed(status=STATUS_DONE)

        with self.captureOnCommitCallbacks(execute=True):
            result = complete_feed(feed)

        self.assertFalse(result)
        mock_delay.assert_not_called()

    def test_queue_is_empty_helper(self):
        feed = self._feed()
        self.assertTrue(queue_is_empty(feed.pk))

        SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='Q', product=None, skipped=False, data={}
        )
        self.assertFalse(queue_is_empty(feed.pk))
