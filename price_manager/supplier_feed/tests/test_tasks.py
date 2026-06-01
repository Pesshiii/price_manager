"""Tests for supplier_feed Celery task run_feed_matching_task.

Behaviors under test:
  - Status transitions: processing → matched / partial / error.
  - Lock: a second call with the same feed_id is silently skipped.

``matcher.run_matching`` and ``_read_rows_from_sessions`` are both mocked so
these tests focus purely on task orchestration, not matching logic (which lives
in test_matcher.py).
"""
from __future__ import annotations

import math
import tempfile
from unittest.mock import patch, MagicMock

import pandas as pd

from django.core.cache import cache
from django.test import TestCase, override_settings

from supplier_feed.models import SupplierFeed, STATUS_MATCHED, STATUS_PARTIAL, STATUS_ERROR
from supplier_feed.tasks import run_feed_matching_task
from .fixtures import make_feed_mapping, make_supplier

_MATCHER_PATH = 'supplier_feed.tasks.matcher.run_matching'
_READ_ROWS_PATH = 'supplier_feed.tasks._read_rows_from_sessions'


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='sf_task_test_'),
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class FeedMatchingTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supplier = make_supplier(name='Task Supplier')
        cls.mapping = make_feed_mapping(
            supplier=cls.supplier,
            supplier_sku_column='article',
        )

    def _make_feed(self, status='processing'):
        return SupplierFeed.objects.create(
            supplier=self.supplier,
            feed_mapping=self.mapping,
            status=status,
        )

    # ── Cycle 5: status → matched ─────────────────────────────────────────────

    def test_task_sets_matched_when_queue_is_empty(self):
        """All rows matched → feed.status becomes 'matched'."""
        feed = self._make_feed()

        with patch(_MATCHER_PATH, return_value={'matched': 3, 'queued': 0}):
            with patch(_READ_ROWS_PATH, return_value=[{'article': 'X'}]):
                run_feed_matching_task(feed.pk)

        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_MATCHED)
        self.assertEqual(feed.error, '')

    # ── Cycle 6: status → partial ─────────────────────────────────────────────

    def test_task_sets_partial_when_queue_not_empty(self):
        """Some rows unmatched → feed.status becomes 'partial'."""
        feed = self._make_feed()

        with patch(_MATCHER_PATH, return_value={'matched': 2, 'queued': 1}):
            with patch(_READ_ROWS_PATH, return_value=[{}]):
                run_feed_matching_task(feed.pk)

        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_PARTIAL)

    # ── Cycle 7: status → error ───────────────────────────────────────────────

    def test_task_sets_error_status_on_exception(self):
        """Exception inside task → feed.status='error', feed.error set."""
        feed = self._make_feed()

        with patch(_READ_ROWS_PATH, side_effect=RuntimeError('boom')):
            run_feed_matching_task(feed.pk)

        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_ERROR)
        self.assertIn('boom', feed.error)

    def test_task_sets_error_when_matcher_raises(self):
        """Exception from matcher → feed.status='error'."""
        feed = self._make_feed()

        with patch(_MATCHER_PATH, side_effect=ValueError('bad data')):
            with patch(_READ_ROWS_PATH, return_value=[{}]):
                run_feed_matching_task(feed.pk)

        feed.refresh_from_db()
        self.assertEqual(feed.status, STATUS_ERROR)
        self.assertIn('bad data', feed.error)

    # ── Cycle 8: lock ─────────────────────────────────────────────────────────

    def test_second_call_with_same_feed_is_skipped(self):
        """If lock already held, task returns early without touching the feed."""
        feed = self._make_feed()
        lock_key = f'supplier-feed-matching:{feed.pk}'
        cache.add(lock_key, '1', timeout=3600)
        try:
            with patch(_MATCHER_PATH) as mock_matching:
                run_feed_matching_task(feed.pk)
            mock_matching.assert_not_called()
        finally:
            cache.delete(lock_key)

        feed.refresh_from_db()
        self.assertEqual(feed.status, 'processing')  # unchanged

    def test_lock_is_released_after_success(self):
        """After a successful run, the lock key must be removed."""
        feed = self._make_feed()
        lock_key = f'supplier-feed-matching:{feed.pk}'

        with patch(_MATCHER_PATH, return_value={'matched': 1, 'queued': 0}):
            with patch(_READ_ROWS_PATH, return_value=[{}]):
                run_feed_matching_task(feed.pk)

        # Lock should be gone — a new run would be accepted
        self.assertIsNone(cache.get(lock_key))

    def test_lock_is_released_after_error(self):
        """Lock must be released even when the task fails."""
        feed = self._make_feed()
        lock_key = f'supplier-feed-matching:{feed.pk}'

        with patch(_READ_ROWS_PATH, side_effect=RuntimeError('fail')):
            run_feed_matching_task(feed.pk)

        self.assertIsNone(cache.get(lock_key))

    # ── Extra: nonexistent feed ───────────────────────────────────────────────

    def test_missing_feed_does_not_raise(self):
        """Task called with nonexistent feed_id returns silently."""
        run_feed_matching_task(999_999_999)  # must not raise


class ReadRowsNanSanitizationTests(TestCase):
    """_read_rows_from_sessions must replace NaN/NaT with None.

    Without sanitization, float NaN ends up in SupplierFeedEntry.data as the
    bare token "NaN", which PostgreSQL rejects as invalid JSON.
    """

    def test_nan_values_become_none(self):
        from supplier_feed.tasks import _read_rows_from_sessions

        df_with_nan = pd.DataFrame([
            {'article': 'SKU-1', 'price': float('nan'), 'stock': 10},
            {'article': 'SKU-2', 'price': 99.0,         'stock': float('nan')},
        ])

        feed = MagicMock()
        feed.session_ids = ['session-abc']
        feed.feed_mapping.dataframe = MagicMock()

        with patch('supplier_feed.tasks.session_store.open_session_file', return_value=MagicMock()):
            with patch('supplier_feed.tasks.dataframe_services.apply', return_value=df_with_nan):
                rows = _read_rows_from_sessions(feed)

        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]['price'])
        self.assertIsNone(rows[1]['stock'])
        # Non-NaN values must be preserved
        self.assertEqual(rows[0]['stock'], 10)
        self.assertEqual(rows[1]['price'], 99.0)

    def test_non_nan_values_are_preserved(self):
        from supplier_feed.tasks import _read_rows_from_sessions

        df_clean = pd.DataFrame([{'article': 'A', 'price': 5.5, 'name': 'Widget'}])

        feed = MagicMock()
        feed.session_ids = ['session-xyz']
        feed.feed_mapping.dataframe = MagicMock()

        with patch('supplier_feed.tasks.session_store.open_session_file', return_value=MagicMock()):
            with patch('supplier_feed.tasks.dataframe_services.apply', return_value=df_clean):
                rows = _read_rows_from_sessions(feed)

        self.assertEqual(rows, [{'article': 'A', 'price': 5.5, 'name': 'Widget'}])
