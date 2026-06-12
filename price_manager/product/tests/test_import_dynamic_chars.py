"""EAV-style dynamic characteristics in the mapping step.

The mapping ships a ``dynamic_characteristics`` list of
``{name_column, value_column, unit_column?}`` specs. For every import row
we read the cells of those columns, slugify the name → CharacteristicType
(get_or_create with value_type='string'), write the value into
``Product.characteristics[slug]`` and let the existing auto-link M2M code
attach the type to the row's category (if any). The unit is "first-write
wins" on the type: if the existing type has an empty unit and an entry
ships one, we backfill; otherwise we never overwrite.
"""
from __future__ import annotations

import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from product.models import CharacteristicType, Product

from .fixtures import csv_instructions, csv_upload

SESSION_URL = 'dataframe_api:session-create'
IMPORT_COMMIT_URL = 'product_api:import-commit'
IMPORT_JOB_URL = 'product_api:import-job'


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='prod_import_dyn_'),
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class DynamicCharacteristicsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)

    def _upload(self, rows):
        resp = self.client.post(reverse(SESSION_URL), {'file': csv_upload(rows)})
        self.assertEqual(resp.status_code, 201)
        return resp.json()['session_id']

    def _commit(self, sid, mapping):
        return self.client.post(
            reverse(IMPORT_COMMIT_URL),
            {'session_id': sid, 'instructions': csv_instructions(), 'mapping': mapping},
            content_type='application/json',
        )

    def test_dynamic_chars_auto_create_types_with_cyrillic_slugs(self):
        sid = self._upload([
            ['sku', 'name', 'attr_name', 'attr_value', 'attr_unit'],
            ['S1', 'Дрель', 'Цвет', 'красный', ''],
            ['S1', 'Дрель', 'Вес', '5', 'кг'],
            ['S2', 'Молоток', 'Материал', 'сталь', ''],
        ])
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'dynamic_characteristics': [
                {'name_column': 'attr_name', 'value_column': 'attr_value', 'unit_column': 'attr_unit'},
            ],
        }
        resp = self._commit(sid, mapping)
        self.assertEqual(resp.status_code, 202, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['status'], 'success', body)
        # 3 rows arrive; SKU upsert means S1 has the latest dynamic char.
        self.assertEqual(Product.objects.count(), 2)

        # Three types auto-created with cyrillic slugs.
        for slug, label, unit in [('цвет', 'Цвет', ''), ('вес', 'Вес', 'кг'), ('материал', 'Материал', '')]:
            ct = CharacteristicType.objects.get(name=slug)
            self.assertEqual(ct.label, label)
            self.assertEqual(ct.value_type, CharacteristicType.VALUE_STRING)
            self.assertEqual(ct.unit, unit)

        # S1 was upserted twice — last commit row's chars survive.
        s1 = Product.objects.get(sku='S1')
        s2 = Product.objects.get(sku='S2')
        self.assertEqual(s1.characteristics.get('вес'), '5')
        self.assertEqual(s2.characteristics.get('материал'), 'сталь')

    def test_unit_is_first_write_wins(self):
        # No type yet → first entry's unit ('kg') wins; 'lb' from a later row ignored.
        sid = self._upload([
            ['sku', 'name', 'attr_name', 'attr_value', 'attr_unit'],
            ['S1', 'A', 'weight', '5', 'kg'],
            ['S2', 'B', 'weight', '10', 'lb'],
        ])
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'dynamic_characteristics': [
                {'name_column': 'attr_name', 'value_column': 'attr_value', 'unit_column': 'attr_unit'},
            ],
        }
        resp = self._commit(sid, mapping)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(CharacteristicType.objects.get(name='weight').unit, 'kg')

    def test_existing_unit_never_overwritten(self):
        CharacteristicType.objects.create(
            name='weight', label='Вес', value_type='string', unit='kg',
        )
        sid = self._upload([
            ['sku', 'name', 'attr_name', 'attr_value', 'attr_unit'],
            ['S1', 'A', 'weight', '5', 'lb'],
        ])
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'dynamic_characteristics': [
                {'name_column': 'attr_name', 'value_column': 'attr_value', 'unit_column': 'attr_unit'},
            ],
        }
        resp = self._commit(sid, mapping)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(CharacteristicType.objects.get(name='weight').unit, 'kg')

    def test_empty_cells_silently_skipped(self):
        sid = self._upload([
            ['sku', 'name', 'attr_name', 'attr_value', 'attr_unit'],
            ['S1', 'A', '', 'orphan-value', ''],
            ['S2', 'B', 'color', '', ''],
            ['S3', 'C', 'color', 'red', ''],
        ])
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'dynamic_characteristics': [
                {'name_column': 'attr_name', 'value_column': 'attr_value', 'unit_column': 'attr_unit'},
            ],
        }
        resp = self._commit(sid, mapping)
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body['status'], 'success', body)
        self.assertEqual(body['result']['created'], 3)
        # Only one type created — empty name/value pairs are skipped.
        self.assertEqual(CharacteristicType.objects.count(), 1)
        self.assertTrue(CharacteristicType.objects.filter(name='color').exists())
        # S1, S2 have empty characteristics; S3 has color=red.
        self.assertEqual(Product.objects.get(sku='S1').characteristics, {})
        self.assertEqual(Product.objects.get(sku='S2').characteristics, {})
        self.assertEqual(Product.objects.get(sku='S3').characteristics, {'color': 'red'})

    def test_static_mapping_wins_on_slug_collision(self):
        # Existing type 'color' with a strict choice list.
        CharacteristicType.objects.create(
            name='color', label='Цвет', value_type='choice', options=['red', 'blue'],
        )
        sid = self._upload([
            ['sku', 'name', 'color', 'attr_name', 'attr_value'],
            ['S1', 'A', 'red', 'color', 'green'],  # dynamic would conflict with static
        ])
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'characteristics': {'color': {'column': 'color'}},
            'dynamic_characteristics': [
                {'name_column': 'attr_name', 'value_column': 'attr_value'},
            ],
        }
        resp = self._commit(sid, mapping)
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body['status'], 'success', body)
        # Static value wins; dynamic 'green' is dropped (slug collides on 'color').
        self.assertEqual(Product.objects.get(sku='S1').characteristics, {'color': 'red'})

    def test_long_unit_and_name_are_truncated(self):
        """Supplier files routinely ship free-form text longer than
        CharacteristicType.unit's 32-char limit. Importer must truncate
        instead of crashing with `value too long for type character varying(32)`.
        """
        long_unit = 'миллиграмм на квадратный сантиметр в секунду'  # > 32 chars
        long_name = 'A' * 400  # > 255 chars for label
        sid = self._upload([
            ['sku', 'name', 'attr_name', 'attr_value', 'attr_unit'],
            ['S1', 'A', long_name, '1', long_unit],
        ])
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'dynamic_characteristics': [
                {'name_column': 'attr_name', 'value_column': 'attr_value', 'unit_column': 'attr_unit'},
            ],
        }
        resp = self._commit(sid, mapping)
        self.assertEqual(resp.status_code, 202, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['status'], 'success', body)
        ct = CharacteristicType.objects.get()
        self.assertEqual(ct.unit, long_unit[:32])
        self.assertEqual(ct.label, long_name[:255])

    def test_dynamic_chars_autolink_to_category(self):
        sid = self._upload([
            ['sku', 'name', 'category', 'attr_name', 'attr_value'],
            ['S1', 'A', 'Шурупы', 'Цвет', 'красный'],
        ])
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'category': {'column': 'category'},
            'dynamic_characteristics': [
                {'name_column': 'attr_name', 'value_column': 'attr_value'},
            ],
        }
        resp = self._commit(sid, mapping)
        self.assertEqual(resp.status_code, 202)
        ct = CharacteristicType.objects.get(name='цвет')
        self.assertTrue(ct.categories.filter(name='Шурупы').exists())
