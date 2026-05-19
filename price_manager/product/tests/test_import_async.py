"""Async import job tests: 202 dispatch, polling, auth isolation, auto-link M2M."""
from __future__ import annotations

import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from product.models import Category, CharacteristicType, ImportJob, Product

from .fixtures import (
    DEFAULT_HEADER,
    csv_instructions,
    csv_upload,
    default_mapping,
    make_char_type,
)

from unittest.mock import patch

from dataframe import sessions as session_store

from product import importer as product_importer
from product import tasks as product_tasks

SESSION_URL = 'dataframe_api:session-create'
IMPORT_PREVIEW_URL = 'product_api:import-preview'
IMPORT_COMMIT_URL = 'product_api:import-commit'
IMPORT_JOB_URL = 'product_api:import-job'


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='prod_import_async_'),
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class AsyncImportFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u1', password='p')
        cls.other = User.objects.create_user(username='u2', password='p')
        make_char_type('color', CharacteristicType.VALUE_STRING)
        make_char_type('weight', CharacteristicType.VALUE_INTEGER)

    def setUp(self):
        self.client.force_login(self.user)

    def _upload(self, rows):
        resp = self.client.post(reverse(SESSION_URL), {'file': csv_upload(rows)})
        self.assertEqual(resp.status_code, 201)
        return resp.json()['session_id']

    def _post(self, url_name, sid, mapping=None):
        return self.client.post(
            reverse(url_name),
            {
                'session_id': sid,
                'instructions': csv_instructions(),
                'mapping': mapping or default_mapping(),
            },
            content_type='application/json',
        )

    def test_preview_returns_202_with_job_envelope(self):
        sid = self._upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'red', '1']])
        resp = self._post(IMPORT_PREVIEW_URL, sid)
        self.assertEqual(resp.status_code, 202, resp.content[:300])
        body = resp.json()
        self.assertIn('id', body)
        self.assertEqual(body['kind'], 'preview')
        # Eager mode → already done by the time the response is built
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['result']['total'], 1)

    def test_commit_returns_202_and_polling_shows_success(self):
        sid = self._upload([
            DEFAULT_HEADER,
            ['S1', 'Дрель', 'Инструменты', 'Acme', 'red', '1500'],
        ])
        resp = self._post(IMPORT_COMMIT_URL, sid)
        self.assertEqual(resp.status_code, 202)
        job_id = resp.json()['id']

        poll = self.client.get(reverse(IMPORT_JOB_URL, args=[job_id]))
        self.assertEqual(poll.status_code, 200)
        body = poll.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['result']['created'], 1)
        self.assertIsNotNone(body['finished_at'])

        self.assertEqual(Product.objects.count(), 1)

    def test_job_access_isolated_per_user(self):
        sid = self._upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'red', '1']])
        job_id = self._post(IMPORT_COMMIT_URL, sid).json()['id']

        self.client.force_login(self.other)
        resp = self.client.get(reverse(IMPORT_JOB_URL, args=[job_id]))
        self.assertEqual(resp.status_code, 404)

    def test_unknown_job_returns_404(self):
        resp = self.client.get(
            reverse(IMPORT_JOB_URL, args=['00000000-0000-0000-0000-000000000000'])
        )
        self.assertEqual(resp.status_code, 404)

    def test_missing_session_returns_404_without_creating_job(self):
        resp = self._post(IMPORT_PREVIEW_URL, 'no-such-session')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(ImportJob.objects.count(), 0)

    def test_commit_writes_stage_transitions(self):
        """During commit_rows the job's stage should be 'Записываем в БД'."""
        sid = self._upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'red', '1']])

        observed: dict[str, str] = {}
        original_commit_rows = product_importer.commit_rows

        def spying_commit_rows(results):
            job = ImportJob.objects.filter(status=ImportJob.STATUS_RUNNING).order_by('-created_at').first()
            if job is not None:
                job.refresh_from_db(fields=['stage'])
                observed['stage_during_commit'] = job.stage
            return original_commit_rows(results)

        with patch.object(product_tasks, 'commit_rows', side_effect=spying_commit_rows):
            resp = self._post(IMPORT_COMMIT_URL, sid)

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(observed.get('stage_during_commit'), product_tasks.STAGE_WRITING_DB)
        job = ImportJob.objects.get(pk=resp.json()['id'])
        self.assertEqual(job.status, ImportJob.STATUS_SUCCESS)
        self.assertEqual(job.stage, '')

    def test_commit_invalidates_session_after_success(self):
        sid = self._upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'red', '1']])
        resp = self._post(IMPORT_COMMIT_URL, sid)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['status'], 'success')
        with self.assertRaises(FileNotFoundError):
            session_store.open_session_file(sid)

    def test_commit_in_chunks_succeeds_for_large_input(self):
        """Chunked commit: rows > batch_size still persists every valid row."""
        rows = [DEFAULT_HEADER]
        for i in range(1, 1201):
            rows.append([f'S{i}', f'N{i}', 'Cat', 'Brandy', 'red', str(i)])
        sid = self._upload(rows)
        with patch.object(product_importer, 'IMPORT_COMMIT_BATCH_SIZE', 250):
            resp = self._post(IMPORT_COMMIT_URL, sid)
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['result']['created'], 1200)
        self.assertEqual(Product.objects.count(), 1200)

    def test_pipeline_error_records_error_status(self):
        sid = self._upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'red', '1']])
        bad_instructions = {
            'reader': {'func': 'read_csv', 'args': {}},
            'transforms': [{'func': 'no_such_transform', 'args': {}}],
        }
        resp = self.client.post(
            reverse(IMPORT_COMMIT_URL),
            {'session_id': sid, 'instructions': bad_instructions, 'mapping': default_mapping()},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 202)
        job = ImportJob.objects.get(pk=resp.json()['id'])
        self.assertEqual(job.status, ImportJob.STATUS_ERROR)
        self.assertTrue(job.error)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='prod_import_autolink_'),
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class CharacteristicCategoryAutoLinkTests(TestCase):
    """commit auto-attaches CharacteristicType ↔ Category M2M for each (cat, char) pair seen."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)

    def _commit(self, rows, mapping):
        resp = self.client.post(reverse(SESSION_URL), {'file': csv_upload(rows)})
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        sid = resp.json()['session_id']
        return self.client.post(
            reverse(IMPORT_COMMIT_URL),
            {'session_id': sid, 'instructions': csv_instructions(), 'mapping': mapping},
            content_type='application/json',
        )

    def test_autolink_creates_m2m_link_after_commit(self):
        make_char_type('color', CharacteristicType.VALUE_STRING)
        rows = [
            ['sku', 'name', 'category', 'color'],
            ['S1', 'Шуруп', 'Шурупы', 'красный'],
        ]
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'category': {'column': 'category'},
            'characteristics': {'color': {'column': 'color'}},
        }
        resp = self._commit(rows, mapping)
        self.assertEqual(resp.status_code, 202, resp.content[:300])

        cat = Category.objects.get(name='Шурупы')
        ct = CharacteristicType.objects.get(name='color')
        self.assertIn(cat, ct.categories.all())

    def test_autolink_is_idempotent_across_rows(self):
        """Many rows with same (category, characteristic) shouldn't error or duplicate."""
        make_char_type('color', CharacteristicType.VALUE_STRING)
        rows = [['sku', 'name', 'category', 'color']] + [
            [f'S{i}', f'N{i}', 'Шурупы', 'красный'] for i in range(5)
        ]
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'category': {'column': 'category'},
            'characteristics': {'color': {'column': 'color'}},
        }
        resp = self._commit(rows, mapping)
        self.assertEqual(resp.status_code, 202)

        cat = Category.objects.get(name='Шурупы')
        ct = CharacteristicType.objects.get(name='color')
        # M2M membership unique by definition; just check the link exists once
        self.assertEqual(ct.categories.filter(pk=cat.pk).count(), 1)

    def test_autolink_skips_when_value_empty(self):
        make_char_type('color', CharacteristicType.VALUE_STRING)
        rows = [
            ['sku', 'name', 'category', 'color'],
            ['S1', 'N', 'Гайки', ''],
        ]
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'category': {'column': 'category'},
            'characteristics': {'color': {'column': 'color'}},
        }
        resp = self._commit(rows, mapping)
        self.assertEqual(resp.status_code, 202)
        ct = CharacteristicType.objects.get(name='color')
        self.assertFalse(ct.categories.filter(name='Гайки').exists())

    def test_autolink_skips_when_category_missing(self):
        make_char_type('color', CharacteristicType.VALUE_STRING)
        rows = [
            ['sku', 'name', 'color'],
            ['S1', 'N', 'красный'],
        ]
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'characteristics': {'color': {'column': 'color'}},
        }
        resp = self._commit(rows, mapping)
        self.assertEqual(resp.status_code, 202)
        ct = CharacteristicType.objects.get(name='color')
        self.assertEqual(ct.categories.count(), 0)
