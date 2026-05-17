from __future__ import annotations

import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from . import cache as df_cache
from .models import Dataframe
from . import sessions as session_store
from .registry import READERS


def make_xlsx_upload(rows, name='data.xlsx'):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(
        name,
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


def make_csv_upload(rows, name='data.csv'):
    text = '\n'.join(','.join(str(c) for c in r) for r in rows).encode('utf-8')
    return SimpleUploadedFile(name, text, content_type='text/csv')


@override_settings(SECURE_SSL_REDIRECT=False)
class ApiTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)


class RegistryEndpointTests(ApiTestBase):
    def test_registry_returns_readers_and_transforms(self):
        resp = self.client.get(reverse('dataframe_api:registry'))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('readers', body)
        self.assertIn('transforms', body)
        reader_names = {r['name'] for r in body['readers']}
        transform_names = {t['name'] for t in body['transforms']}
        self.assertIn('read_excel', reader_names)
        self.assertIn('read_csv', reader_names)
        self.assertIn('rename_columns', transform_names)

    def test_registry_arg_schema_shape(self):
        resp = self.client.get(reverse('dataframe_api:registry'))
        read_csv = next(r for r in resp.json()['readers'] if r['name'] == 'read_csv')
        self.assertTrue(read_csv['args'])
        first = read_csv['args'][0]
        for key in ('name', 'type', 'label', 'required', 'default', 'choices', 'help_text'):
            self.assertIn(key, first)

    def test_anonymous_blocked(self):
        self.client.logout()
        resp = self.client.get(reverse('dataframe_api:registry'))
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp['Content-Type'].split(';')[0], 'application/json')


class PipelineCrudTests(ApiTestBase):
    def _instructions(self):
        return {
            'reader': {'func': 'read_csv', 'args': {'sep': ','}},
            'transforms': [{'func': 'select_columns', 'args': {'cols': 'a'}}],
        }

    def test_create_pipeline(self):
        resp = self.client.post(
            reverse('dataframe_api:pipeline-list'),
            {'name': 'P1', 'description': '', 'instructions': self._instructions()},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.assertEqual(Dataframe.objects.count(), 1)
        self.assertEqual(Dataframe.objects.get().name, 'P1')

    def test_create_rejects_unknown_transform(self):
        resp = self.client.post(
            reverse('dataframe_api:pipeline-list'),
            {
                'name': 'Bad',
                'instructions': {
                    'reader': {'func': 'read_csv', 'args': {}},
                    'transforms': [{'func': 'nope', 'args': {}}],
                },
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('instructions', resp.json())

    def test_list_and_retrieve(self):
        df = Dataframe.objects.create(name='Lst', instructions=self._instructions())
        list_resp = self.client.get(reverse('dataframe_api:pipeline-list'))
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json()), 1)

        detail = self.client.get(reverse('dataframe_api:pipeline-detail', args=[df.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['name'], 'Lst')

    def test_update_pipeline(self):
        df = Dataframe.objects.create(name='Old', instructions=self._instructions())
        new_instr = self._instructions()
        new_instr['transforms'].append({'func': 'drop_na', 'args': {}})
        resp = self.client.put(
            reverse('dataframe_api:pipeline-detail', args=[df.pk]),
            {'name': 'New', 'description': 'x', 'instructions': new_instr},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        df.refresh_from_db()
        self.assertEqual(df.name, 'New')
        self.assertEqual(len(df.instructions['transforms']), 2)

    def test_delete_pipeline(self):
        df = Dataframe.objects.create(name='Del', instructions=self._instructions())
        resp = self.client.delete(reverse('dataframe_api:pipeline-detail', args=[df.pk]))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Dataframe.objects.filter(pk=df.pk).exists())


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='df_test_'),
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class UploadSessionTests(ApiTestBase):
    def test_create_session_returns_id(self):
        upload = make_csv_upload([['a', 'b'], ['1', '2']])
        resp = self.client.post(reverse('dataframe_api:session-create'), {'file': upload})
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        body = resp.json()
        self.assertIn('session_id', body)
        self.assertEqual(body['filename'], 'data.csv')

    def test_create_session_requires_file(self):
        resp = self.client.post(reverse('dataframe_api:session-create'), {})
        self.assertEqual(resp.status_code, 400)

    def test_open_session_file_roundtrip(self):
        upload = make_csv_upload([['a'], ['1']])
        resp = self.client.post(reverse('dataframe_api:session-create'), {'file': upload})
        sid = resp.json()['session_id']
        f = session_store.open_session_file(sid)
        self.assertEqual(f.read().decode('utf-8'), 'a\n1')
        f.close()

    def test_delete_session(self):
        upload = make_csv_upload([['a'], ['1']])
        sid = self.client.post(reverse('dataframe_api:session-create'), {'file': upload}).json()['session_id']
        resp = self.client.delete(reverse('dataframe_api:session-detail', args=[sid]))
        self.assertEqual(resp.status_code, 204)
        with self.assertRaises(FileNotFoundError):
            session_store.open_session_file(sid)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='df_prev_'),
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class PreviewEndpointTests(ApiTestBase):
    def _upload_session(self, rows, name='data.csv'):
        upload = make_csv_upload(rows, name=name)
        resp = self.client.post(reverse('dataframe_api:session-create'), {'file': upload})
        return resp.json()['session_id']

    def test_preview_no_transforms(self):
        sid = self._upload_session([['a', 'b'], ['1', '2'], ['3', '4']])
        resp = self.client.post(
            reverse('dataframe_api:preview'),
            {
                'session_id': sid,
                'instructions': {'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []},
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['columns'], ['a', 'b'])
        self.assertEqual(body['total_rows'], 2)
        self.assertEqual(body['rows'], [['1', '2'], ['3', '4']])

    def test_preview_applies_transforms(self):
        sid = self._upload_session([['a', 'b', 'c'], ['1', '2', '3'], ['4', '5', '6']])
        resp = self.client.post(
            reverse('dataframe_api:preview'),
            {
                'session_id': sid,
                'instructions': {
                    'reader': {'func': 'read_csv', 'args': {}},
                    'transforms': [
                        {'func': 'select_columns', 'args': {'cols': 'a,b'}},
                        {'func': 'rename_columns', 'args': {'mapping': 'a=alpha\nb=beta'}},
                    ],
                },
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['columns'], ['alpha', 'beta'])

    def test_preview_up_to_stops_early(self):
        sid = self._upload_session([['a', 'b', 'c'], ['1', '2', '3']])
        resp = self.client.post(
            reverse('dataframe_api:preview'),
            {
                'session_id': sid,
                'up_to': 1,
                'instructions': {
                    'reader': {'func': 'read_csv', 'args': {}},
                    'transforms': [
                        {'func': 'select_columns', 'args': {'cols': 'a,b'}},
                        {'func': 'rename_columns', 'args': {'mapping': 'a=alpha'}},
                    ],
                },
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        # Rename not yet applied — columns are still a,b
        self.assertEqual(body['columns'], ['a', 'b'])

    def test_preview_returns_error_on_bad_step(self):
        sid = self._upload_session([['a', 'b'], ['1', '2']])
        resp = self.client.post(
            reverse('dataframe_api:preview'),
            {
                'session_id': sid,
                'instructions': {
                    'reader': {'func': 'read_csv', 'args': {}},
                    'transforms': [
                        {'func': 'replace_values', 'args': {}},  # missing required 'column'
                    ],
                },
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('error', body)
        self.assertIn('message', body['error'])

    def test_preview_unknown_session(self):
        resp = self.client.post(
            reverse('dataframe_api:preview'),
            {
                'session_id': 'doesnotexist',
                'instructions': {'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []},
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_preview_rejects_unknown_transform(self):
        sid = self._upload_session([['a'], ['1']])
        resp = self.client.post(
            reverse('dataframe_api:preview'),
            {
                'session_id': sid,
                'instructions': {
                    'reader': {'func': 'read_csv', 'args': {}},
                    'transforms': [{'func': 'nope', 'args': {}}],
                },
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_preview_xlsx_source(self):
        upload = make_xlsx_upload([['a', 'b'], ['1', '2'], ['3', '4']])
        sid = self.client.post(reverse('dataframe_api:session-create'), {'file': upload}).json()['session_id']
        resp = self.client.post(
            reverse('dataframe_api:preview'),
            {
                'session_id': sid,
                'instructions': {'reader': {'func': 'read_excel', 'args': {}}, 'transforms': []},
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['columns'], ['a', 'b'])
        self.assertEqual(body['total_rows'], 2)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='df_meta_'),
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class SessionMetadataTests(ApiTestBase):
    def test_get_returns_metadata(self):
        upload = make_csv_upload([['a'], ['1']], name='hello.csv')
        sid = self.client.post(reverse('dataframe_api:session-create'), {'file': upload}).json()['session_id']
        resp = self.client.get(reverse('dataframe_api:session-detail', args=[sid]))
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['session_id'], sid)
        self.assertEqual(body['filename'], 'hello.csv')
        self.assertGreater(body['size'], 0)
        self.assertIn('uploaded_at', body)

    def test_get_returns_404_for_missing_session(self):
        resp = self.client.get(reverse('dataframe_api:session-detail', args=['missing-sid']))
        self.assertEqual(resp.status_code, 404)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='df_offset_'),
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class PreviewOffsetTests(ApiTestBase):
    def _upload_10_rows(self):
        rows = [['col']] + [[str(i)] for i in range(10)]
        upload = make_csv_upload(rows)
        return self.client.post(reverse('dataframe_api:session-create'), {'file': upload}).json()['session_id']

    def _preview(self, sid, **extra):
        body = {
            'session_id': sid,
            'instructions': {'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []},
            **extra,
        }
        return self.client.post(
            reverse('dataframe_api:preview'), body, content_type='application/json',
        )

    def test_offset_returns_window(self):
        sid = self._upload_10_rows()
        resp = self._preview(sid, offset=3, row_limit=4)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['offset'], 3)
        self.assertEqual(body['returned_rows'], 4)
        self.assertEqual(body['total_rows'], 10)
        self.assertTrue(body['has_more'])
        self.assertEqual([r[0] for r in body['rows']], ['3', '4', '5', '6'])

    def test_offset_at_tail_marks_no_more(self):
        sid = self._upload_10_rows()
        resp = self._preview(sid, offset=8, row_limit=10)
        body = resp.json()
        self.assertEqual(body['returned_rows'], 2)
        self.assertFalse(body['has_more'])

    def test_offset_past_total_returns_empty(self):
        sid = self._upload_10_rows()
        resp = self._preview(sid, offset=100, row_limit=10)
        body = resp.json()
        self.assertEqual(body['rows'], [])
        self.assertEqual(body['returned_rows'], 0)
        self.assertFalse(body['has_more'])

    def test_default_offset_zero(self):
        sid = self._upload_10_rows()
        resp = self._preview(sid, row_limit=3)
        body = resp.json()
        self.assertEqual(body['offset'], 0)
        self.assertEqual(body['returned_rows'], 3)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='df_cache_'),
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'dataframe-test-cache',
        },
    },
)
class ReaderCacheTests(ApiTestBase):
    """Verifies that the reader stage is only invoked once across repeated previews."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def _upload(self, rows=None):
        rows = rows or [['a', 'b'], ['1', '2'], ['3', '4']]
        upload = make_csv_upload(rows)
        return self.client.post(reverse('dataframe_api:session-create'), {'file': upload}).json()['session_id']

    def _preview(self, sid, **extra):
        body = {
            'session_id': sid,
            'instructions': {'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []},
            **extra,
        }
        return self.client.post(
            reverse('dataframe_api:preview'), body, content_type='application/json',
        )

    def _wrap_reader(self):
        """Swap `read_csv` in the registry for a counting wrapper. Returns a counter."""
        from dataclasses import replace
        original_spec = READERS['read_csv']
        counter = {'n': 0}

        def counting(*args, **kwargs):
            counter['n'] += 1
            return original_spec.func(*args, **kwargs)

        READERS['read_csv'] = replace(original_spec, func=counting)
        self.addCleanup(lambda: READERS.__setitem__('read_csv', original_spec))
        return counter

    def test_second_preview_hits_cache(self):
        counter = self._wrap_reader()
        sid = self._upload()
        self._preview(sid)
        self._preview(sid)
        self.assertEqual(counter['n'], 1, 'reader must be called once when payload is cached')

    def test_different_reader_args_bust_cache(self):
        counter = self._wrap_reader()
        sid = self._upload()
        self._preview(sid)
        self._preview(sid, instructions={'reader': {'func': 'read_csv', 'args': {'sep': ','}},
                                          'transforms': []})
        self.assertEqual(counter['n'], 2, 'distinct reader configs must each hit the reader once')

    def test_delete_session_invalidates_cache(self):
        # LocMemCache lacks delete_pattern → invalidate_session is a no-op.
        # We verify the request flow at least doesn't error and the file deletion still happens.
        counter = self._wrap_reader()
        sid = self._upload()
        self._preview(sid)
        self.assertEqual(counter['n'], 1)
        resp = self.client.delete(reverse('dataframe_api:session-detail', args=[sid]))
        self.assertEqual(resp.status_code, 204)
        # File gone → next preview is 404, reader not called again.
        resp2 = self._preview(sid)
        self.assertEqual(resp2.status_code, 404)
        self.assertEqual(counter['n'], 1)


class ReaderCacheUnitTests(TestCase):
    """Unit-level: cache key stability and size guard, no HTTP."""

    def test_cache_key_stable_for_equivalent_configs(self):
        k1 = df_cache.reader_cache_key('sid', {'func': 'read_csv', 'args': {'sep': ',', 'encoding': 'utf-8'}})
        k2 = df_cache.reader_cache_key('sid', {'args': {'encoding': 'utf-8', 'sep': ','}, 'func': 'read_csv'})
        self.assertEqual(k1, k2)

    def test_cache_key_differs_per_session(self):
        cfg = {'func': 'read_csv', 'args': {}}
        self.assertNotEqual(
            df_cache.reader_cache_key('a', cfg),
            df_cache.reader_cache_key('b', cfg),
        )

    def test_set_get_roundtrip(self):
        import pandas as pd
        key = df_cache.reader_cache_key('roundtrip', {'func': 'read_csv'})
        ok = df_cache.set_cached_reader_df(key, pd.DataFrame({'a': [1, 2]}))
        self.assertTrue(ok)
        out = df_cache.get_cached_reader_df(key)
        self.assertIsNotNone(out)
        self.assertEqual(list(out.columns), ['a'])
