from __future__ import annotations

import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from .models import Dataframe
from . import sessions as session_store


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
