import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dataframe import sessions as session_store
from product.models import Brand, Category, CharacteristicType, Product


def make_csv_upload(rows, name='data.csv'):
    text = '\n'.join(','.join(str(c) for c in r) for r in rows).encode('utf-8')
    return SimpleUploadedFile(name, text, content_type='text/csv')


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='prod_import_'),
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class ImportFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        CharacteristicType.objects.create(name='color', label='Цвет', value_type='string')
        CharacteristicType.objects.create(name='weight', label='Вес', value_type='integer')

    def setUp(self):
        self.client.force_login(self.user)

    def _upload(self, rows):
        upload = make_csv_upload(rows)
        resp = self.client.post(reverse('dataframe_api:session-create'), {'file': upload})
        return resp.json()['session_id']

    def _mapping(self):
        return {
            'sku':  {'column': 'sku'},
            'name': {'column': 'name'},
            'category': {'column': 'category'},
            'brand':    {'column': 'brand'},
            'status':   {'const': 'active'},
            'characteristics': {
                'color':  {'column': 'color'},
                'weight': {'column': 'weight'},
            },
        }

    def _instructions(self):
        return {'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []}

    def test_preview_returns_payloads(self):
        sid = self._upload([
            ['sku', 'name', 'category', 'brand', 'color', 'weight'],
            ['S1', 'Дрель', 'Инструменты', 'Acme', 'red', '1500'],
            ['S2', 'Чехол', 'Аксессуары', 'Brandy', 'blue', '50'],
        ])
        resp = self.client.post(
            reverse('product_api:import-preview'),
            {'session_id': sid, 'instructions': self._instructions(), 'mapping': self._mapping()},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['total'], 2)
        self.assertEqual(body['valid'], 2)
        first = body['rows'][0]['payload']
        self.assertEqual(first['sku'], 'S1')
        self.assertEqual(first['category'], 'Инструменты')
        self.assertEqual(first['characteristics'], {'color': 'red', 'weight': 1500})

    def test_commit_creates_records(self):
        sid = self._upload([
            ['sku', 'name', 'category', 'brand', 'color', 'weight'],
            ['S1', 'Дрель', 'Инструменты', 'Acme', 'red', '1500'],
        ])
        resp = self.client.post(
            reverse('product_api:import-commit'),
            {'session_id': sid, 'instructions': self._instructions(), 'mapping': self._mapping()},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['created'], 1)
        self.assertEqual(body['updated'], 0)
        self.assertEqual(Product.objects.count(), 1)
        self.assertTrue(Category.objects.filter(name='Инструменты').exists())
        self.assertTrue(Brand.objects.filter(name='Acme').exists())
        p = Product.objects.get(sku='S1')
        self.assertEqual(p.characteristics, {'color': 'red', 'weight': 1500})

    def test_commit_upserts_by_sku(self):
        sid1 = self._upload([
            ['sku', 'name', 'category', 'brand', 'color', 'weight'],
            ['S1', 'Дрель', 'Инструменты', 'Acme', 'red', '1500'],
        ])
        self.client.post(
            reverse('product_api:import-commit'),
            {'session_id': sid1, 'instructions': self._instructions(), 'mapping': self._mapping()},
            content_type='application/json',
        )
        sid2 = self._upload([
            ['sku', 'name', 'category', 'brand', 'color', 'weight'],
            ['S1', 'Дрель PRO', 'Инструменты', 'Acme', 'blue', '1600'],
        ])
        resp = self.client.post(
            reverse('product_api:import-commit'),
            {'session_id': sid2, 'instructions': self._instructions(), 'mapping': self._mapping()},
            content_type='application/json',
        )
        body = resp.json()
        self.assertEqual(body['updated'], 1)
        self.assertEqual(Product.objects.count(), 1)
        p = Product.objects.get(sku='S1')
        self.assertEqual(p.name, 'Дрель PRO')
        self.assertEqual(p.characteristics['color'], 'blue')

    def test_commit_collects_invalid_rows(self):
        sid = self._upload([
            ['sku', 'name', 'category', 'brand', 'color', 'weight'],
            ['S1', 'OK', 'C', 'B', 'red', '5'],
            ['', 'NoSku', 'C', 'B', 'red', '5'],  # missing sku → invalid
            ['S3', 'BadWeight', 'C', 'B', 'red', 'notanumber'],  # invalid characteristic
        ])
        resp = self.client.post(
            reverse('product_api:import-commit'),
            {'session_id': sid, 'instructions': self._instructions(), 'mapping': self._mapping()},
            content_type='application/json',
        )
        body = resp.json()
        self.assertEqual(body['created'], 1)
        self.assertEqual(body['skipped'], 2)
        self.assertEqual(Product.objects.count(), 1)

    def test_preview_session_not_found(self):
        resp = self.client.post(
            reverse('product_api:import-preview'),
            {'session_id': 'missing', 'instructions': self._instructions(), 'mapping': self._mapping()},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)
