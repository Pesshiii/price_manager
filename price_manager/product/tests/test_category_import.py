"""Tests for the category import flow.

Covers:
  category_importer.apply_mapping  — pure in-memory path parsing
  category_importer.commit_rows    — MPTT get_or_create chain
  POST /api/products/categories/import/preview/
  POST /api/products/categories/import/commit/
  GET  /api/products/categories/import/jobs/<uuid>/
"""
from __future__ import annotations

import tempfile

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from product.category_importer import (
    STATUS_EXISTS,
    STATUS_INVALID,
    STATUS_NEW,
    CategoryRowResult,
    apply_mapping,
    commit_rows,
)
from product.models import Category, ImportJob

from .fixtures import csv_upload, csv_instructions

CATEGORY_PREVIEW_URL = 'product_api:category-import-preview'
CATEGORY_COMMIT_URL = 'product_api:category-import-commit'
CATEGORY_JOB_URL = 'product_api:category-import-job'
SESSION_URL = 'dataframe_api:session-create'


# ---------------------------------------------------------------------------
# Unit tests — apply_mapping
# ---------------------------------------------------------------------------
class ApplyMappingTests(TestCase):
    def _df(self, rows, column='path'):
        return pd.DataFrame(rows, columns=[column])

    def test_simple_two_level_path(self):
        df = self._df([['Электроника > Смартфоны']])
        results = apply_mapping(df, {'path_column': 'path', 'separator': '>'})
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.segments, ['Электроника', 'Смартфоны'])
        self.assertEqual(r.status, STATUS_NEW)

    def test_single_segment(self):
        df = self._df([['Электроника']])
        results = apply_mapping(df, {'path_column': 'path'})
        self.assertEqual(results[0].segments, ['Электроника'])
        self.assertEqual(results[0].status, STATUS_NEW)

    def test_custom_separator(self):
        df = self._df([['A|B|C']])
        results = apply_mapping(df, {'path_column': 'path', 'separator': '|'})
        self.assertEqual(results[0].segments, ['A', 'B', 'C'])

    def test_strips_whitespace_around_segments(self):
        df = self._df([['  Инструменты  >  Дрели  ']])
        results = apply_mapping(df, {'path_column': 'path'})
        self.assertEqual(results[0].segments, ['Инструменты', 'Дрели'])

    def test_empty_path_is_invalid(self):
        df = self._df([[''], [None]])
        results = apply_mapping(df, {'path_column': 'path'})
        self.assertEqual(results[0].status, STATUS_INVALID)
        self.assertEqual(results[1].status, STATUS_INVALID)

    def test_empty_segment_is_invalid(self):
        df = self._df([['A > > B']])
        results = apply_mapping(df, {'path_column': 'path'})
        self.assertEqual(results[0].status, STATUS_INVALID)

    def test_missing_column_is_invalid(self):
        df = self._df([['x']], column='other')
        results = apply_mapping(df, {'path_column': 'path'})
        self.assertEqual(results[0].status, STATUS_INVALID)

    def test_existing_path_is_status_exists(self):
        root = Category.objects.create(name='Корень', slug='koren')
        Category.objects.create(name='Ребёнок', slug='rebyonok', parent=root)
        df = self._df([['Корень > Ребёнок']])
        results = apply_mapping(df, {'path_column': 'path'})
        self.assertEqual(results[0].status, STATUS_EXISTS)

    def test_partially_existing_path_is_status_new(self):
        Category.objects.create(name='Корень', slug='koren2')
        df = self._df([['Корень > НовыйРебёнок']])
        results = apply_mapping(df, {'path_column': 'path'})
        self.assertEqual(results[0].status, STATUS_NEW)

    def test_index_matches_dataframe_index(self):
        df = self._df([['A'], ['B'], ['C']])
        results = apply_mapping(df, {'path_column': 'path'})
        self.assertEqual([r.index for r in results], [0, 1, 2])


# ---------------------------------------------------------------------------
# Unit tests — commit_rows
# ---------------------------------------------------------------------------
class CommitRowsTests(TestCase):
    def _new(self, path, segments):
        return CategoryRowResult(index=0, path=path, segments=segments, status=STATUS_NEW)

    def _exists(self, path, segments):
        return CategoryRowResult(index=0, path=path, segments=segments, status=STATUS_EXISTS)

    def _invalid(self):
        return CategoryRowResult(index=0, path='', segments=[], status=STATUS_INVALID)

    def test_creates_chain(self):
        results = [self._new('A > B > C', ['A', 'B', 'C'])]
        summary = commit_rows(results)
        self.assertEqual(summary['created'], 3)
        self.assertEqual(summary['skipped'], 0)
        self.assertEqual(summary['invalid'], 0)
        self.assertEqual(summary['errors'], [])
        self.assertTrue(Category.objects.filter(name='A', parent=None).exists())
        a = Category.objects.get(name='A', parent=None)
        b = Category.objects.get(name='B', parent=a)
        self.assertTrue(Category.objects.filter(name='C', parent=b).exists())

    def test_reuses_existing_intermediate_node(self):
        root = Category.objects.create(name='Root', slug='root')
        results = [self._new('Root > New', ['Root', 'New'])]
        summary = commit_rows(results)
        self.assertEqual(summary['created'], 1)
        self.assertEqual(Category.objects.filter(name='Root').count(), 1)
        self.assertTrue(Category.objects.filter(name='New', parent=root).exists())

    def test_skips_exists_rows(self):
        results = [self._exists('X', ['X'])]
        summary = commit_rows(results)
        self.assertEqual(summary['skipped'], 1)
        self.assertEqual(summary['created'], 0)
        self.assertFalse(Category.objects.filter(name='X').exists())

    def test_counts_invalid_rows(self):
        results = [self._invalid()]
        summary = commit_rows(results)
        self.assertEqual(summary['invalid'], 1)
        self.assertEqual(summary['created'], 0)

    def test_multiple_paths_share_root(self):
        results = [
            self._new('Root > A', ['Root', 'A']),
            self._new('Root > B', ['Root', 'B']),
        ]
        summary = commit_rows(results)
        # Root created once, A and B each once
        self.assertEqual(summary['created'], 3)
        self.assertEqual(Category.objects.filter(name='Root').count(), 1)

    def test_duplicate_new_paths_idempotent(self):
        results = [
            self._new('X', ['X']),
            self._new('X', ['X']),
        ]
        summary = commit_rows(results)
        self.assertEqual(Category.objects.filter(name='X').count(), 1)
        # second get_or_create returns was_created=False, so counter stays at 1
        self.assertEqual(summary['created'], 1)


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------
@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='cat_import_'),
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class CategoryImportAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='cat_user', password='p')

    def setUp(self):
        self.client.force_login(self.user)

    def _upload(self, rows):
        f = csv_upload(rows)
        resp = self.client.post(reverse(SESSION_URL), {'file': f})
        self.assertEqual(resp.status_code, 201)
        return resp.json()['session_id']

    def _dispatch(self, url_name, sid, mapping, row_limit=200):
        """POST to url_name, then poll the job. Returns (post_resp, poll_resp).

        poll_resp is None when post_resp.status_code != 202.
        """
        payload = {
            'session_id': sid,
            'instructions': csv_instructions(),
            'mapping': mapping,
            'row_limit': row_limit,
        }
        post_resp = self.client.post(reverse(url_name), payload, content_type='application/json')
        if post_resp.status_code != 202:
            return post_resp, None
        job_id = post_resp.json()['id']
        poll_resp = self.client.get(reverse(CATEGORY_JOB_URL, args=[job_id]))
        return post_resp, poll_resp

    def _result(self, poll_resp):
        """Extract result dict from a succeeded job poll response."""
        body = poll_resp.json()
        self.assertEqual(body['status'], 'success', body.get('error', ''))
        return body['result']

    def _mapping(self, column='path', separator='>'):
        return {'path_column': column, 'separator': separator}

    # --- preview ---

    def test_preview_returns_row_statuses(self):
        Category.objects.create(name='Existing', slug='existing')
        sid = self._upload([['path'], ['Existing'], ['New > Leaf'], ['']])
        _, poll_resp = self._dispatch(CATEGORY_PREVIEW_URL, sid, self._mapping())
        result = self._result(poll_resp)
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['exists'], 1)
        self.assertEqual(result['new'], 1)
        self.assertEqual(result['invalid'], 1)

    def test_preview_does_not_write_db(self):
        sid = self._upload([['path'], ['Brand > New Category']])
        self._dispatch(CATEGORY_PREVIEW_URL, sid, self._mapping())
        self.assertFalse(Category.objects.filter(name='Brand').exists())

    def test_preview_row_limit(self):
        rows = [['path']] + [[f'Cat{i}'] for i in range(10)]
        sid = self._upload(rows)
        _, poll_resp = self._dispatch(CATEGORY_PREVIEW_URL, sid, self._mapping(), row_limit=3)
        result = self._result(poll_resp)
        self.assertEqual(result['total'], 10)
        self.assertEqual(result['returned'], 3)
        self.assertEqual(len(result['rows']), 3)

    def test_preview_row_structure(self):
        Category.objects.create(name='ExistingRoot', slug='existing-root')
        sid = self._upload([['path'], ['ExistingRoot'], ['New > Leaf'], ['']])
        _, poll_resp = self._dispatch(CATEGORY_PREVIEW_URL, sid, self._mapping())
        result = self._result(poll_resp)
        rows_by_status = {r['status']: r for r in result['rows']}

        exists_row = rows_by_status[STATUS_EXISTS]
        self.assertIn('path', exists_row)
        self.assertIn('segments', exists_row)
        self.assertNotIn('error', exists_row)

        new_row = rows_by_status[STATUS_NEW]
        self.assertIn('path', new_row)
        self.assertIn('segments', new_row)
        self.assertNotIn('error', new_row)

        invalid_row = rows_by_status[STATUS_INVALID]
        self.assertIn('path', invalid_row)
        self.assertIn('error', invalid_row)

    # --- commit ---

    def test_commit_creates_categories(self):
        sid = self._upload([['path'], ['Электроника > Смартфоны'], ['Электроника > Планшеты']])
        _, poll_resp = self._dispatch(CATEGORY_COMMIT_URL, sid, self._mapping())
        result = self._result(poll_resp)
        self.assertEqual(result['created'], 3)  # Электроника + Смартфоны + Планшеты
        self.assertEqual(result['skipped'], 0)
        self.assertEqual(result['invalid'], 0)
        self.assertEqual(result['errors'], [])
        self.assertTrue(Category.objects.filter(name='Электроника').exists())
        root = Category.objects.get(name='Электроника', parent=None)
        self.assertTrue(Category.objects.filter(name='Смартфоны', parent=root).exists())

    def test_commit_skips_existing(self):
        Category.objects.create(name='Already', slug='already')
        sid = self._upload([['path'], ['Already'], ['New']])
        _, poll_resp = self._dispatch(CATEGORY_COMMIT_URL, sid, self._mapping())
        result = self._result(poll_resp)
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['errors'], [])
        self.assertEqual(Category.objects.filter(name='Already').count(), 1)

    def test_commit_invalid_rows_not_created(self):
        sid = self._upload([['path'], [''], ['Valid']])
        _, poll_resp = self._dispatch(CATEGORY_COMMIT_URL, sid, self._mapping())
        result = self._result(poll_resp)
        self.assertEqual(result['invalid'], 1)
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['errors'], [])

    def test_commit_sets_rows_total_zero_done(self):
        # Category commit sets rows_total once (for the SPA progress bar) but
        # never advances rows_done — the loop has no natural batch boundary.
        sid = self._upload([['path'], ['A'], ['B'], ['C']])
        post_resp, _ = self._dispatch(CATEGORY_COMMIT_URL, sid, self._mapping())
        self.assertEqual(post_resp.status_code, 202)
        job = ImportJob.objects.get(pk=post_resp.json()['id'])
        self.assertEqual(job.rows_total, 3)
        self.assertEqual(job.rows_done, 0)

    def test_commit_error_marks_job_failed(self):
        sid = self._upload([['path'], ['A']])
        bad_instructions = {'reader': {'func': 'nonexistent_reader', 'args': {}}, 'transforms': []}
        payload = {
            'session_id': sid,
            'instructions': bad_instructions,
            'mapping': self._mapping(),
        }
        post_resp = self.client.post(
            reverse(CATEGORY_COMMIT_URL), payload, content_type='application/json'
        )
        self.assertEqual(post_resp.status_code, 202)
        job_id = post_resp.json()['id']
        poll_resp = self.client.get(reverse(CATEGORY_JOB_URL, args=[job_id]))
        body = poll_resp.json()
        self.assertEqual(body['status'], 'error')
        self.assertTrue(body['error'])

    def test_job_is_target_category(self):
        sid = self._upload([['path'], ['X']])
        payload = {
            'session_id': sid,
            'instructions': csv_instructions(),
            'mapping': self._mapping(),
        }
        resp = self.client.post(
            reverse(CATEGORY_COMMIT_URL), payload, content_type='application/json'
        )
        self.assertEqual(resp.status_code, 202)
        job_id = resp.json()['id']
        job = ImportJob.objects.get(pk=job_id)
        self.assertEqual(job.target, ImportJob.TARGET_CATEGORY)

    def test_session_not_found_returns_404(self):
        payload = {
            'session_id': 'no-such-session',
            'instructions': csv_instructions(),
            'mapping': self._mapping(),
        }
        resp = self.client.post(
            reverse(CATEGORY_PREVIEW_URL), payload, content_type='application/json'
        )
        self.assertEqual(resp.status_code, 404)

    def test_job_polling_endpoint(self):
        sid = self._upload([['path'], ['A']])
        payload = {
            'session_id': sid,
            'instructions': csv_instructions(),
            'mapping': self._mapping(),
        }
        post_resp = self.client.post(
            reverse(CATEGORY_COMMIT_URL), payload, content_type='application/json'
        )
        self.assertEqual(post_resp.status_code, 202)
        job_id = post_resp.json()['id']
        poll_resp = self.client.get(reverse(CATEGORY_JOB_URL, args=[job_id]))
        self.assertEqual(poll_resp.status_code, 200)
        self.assertIn('status', poll_resp.json())

    def test_job_polling_requires_owner(self):
        sid = self._upload([['path'], ['X']])
        payload = {
            'session_id': sid,
            'instructions': csv_instructions(),
            'mapping': self._mapping(),
        }
        post_resp = self.client.post(
            reverse(CATEGORY_COMMIT_URL), payload, content_type='application/json'
        )
        self.assertEqual(post_resp.status_code, 202)
        job_id = post_resp.json()['id']

        User = get_user_model()
        other = User.objects.create_user(username='other_cat_user', password='p')
        self.client.force_login(other)
        poll_resp = self.client.get(reverse(CATEGORY_JOB_URL, args=[job_id]))
        self.assertEqual(poll_resp.status_code, 404)
