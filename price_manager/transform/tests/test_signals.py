"""Unit tests for transform.signals — post_save trigger on SupplierFeed."""
from unittest.mock import patch

from django.test import TestCase

from supplier_feed.models import SupplierFeed
from supplier_feed.tests.fixtures import make_feed_mapping


class SupplierFeedSignalTest(TestCase):
    def setUp(self):
        self.fm = make_feed_mapping()

    def _save_with_status(self, status):
        feed = SupplierFeed(supplier=self.fm.supplier, feed_mapping=self.fm, status=status)
        with patch('transform.tasks.run_transform_task.delay') as mock_delay:
            feed.save()
            return mock_delay, feed

    # --- Cycle 6: status='matched' → delay called ---

    def test_matched_status_triggers_delay(self):
        mock_delay, feed = self._save_with_status('matched')
        mock_delay.assert_called_once_with(feed.pk)

    # --- Cycle 7: status='done' → delay called ---

    def test_done_status_triggers_delay(self):
        mock_delay, feed = self._save_with_status('done')
        mock_delay.assert_called_once_with(feed.pk)

    # --- Cycle 8: status='processing' → delay NOT called ---

    def test_processing_status_does_not_trigger(self):
        mock_delay, _ = self._save_with_status('processing')
        mock_delay.assert_not_called()

    # --- Cycle 9: status='draft' → delay NOT called ---

    def test_draft_status_does_not_trigger(self):
        mock_delay, _ = self._save_with_status('draft')
        mock_delay.assert_not_called()
