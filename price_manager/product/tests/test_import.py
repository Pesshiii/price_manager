"""End-to-end tests for the dataframe → product import flow.

Each class drives the four real HTTP endpoints in order:
  POST /api/dataframe/sessions/        (upload)
  POST /api/dataframe/preview/         (optional, raw pipeline output)
  POST /api/products/import/preview/   (mapping → payloads, no commit)
  POST /api/products/import/commit/    (persist)
"""
from __future__ import annotations

import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from product.models import Brand, Category, CharacteristicType, Product

from .fixtures import (
    DEFAULT_HEADER,
    bytes_upload,
    csv_instructions,
    csv_upload,
    default_mapping,
    make_char_type,
    xlsx_instructions,
    xlsx_upload,
)

SESSION_URL = 'dataframe_api:session-create'
PREVIEW_URL = 'dataframe_api:preview'
IMPORT_PREVIEW_URL = 'product_api:import-preview'
IMPORT_COMMIT_URL = 'product_api:import-commit'


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='prod_import_'),
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class BaseImportTests(TestCase):
    """Shared scaffolding: login + endpoint wrappers."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)

    # ---- endpoint wrappers ----
    def upload(self, upload_file):
        resp = self.client.post(reverse(SESSION_URL), {'file': upload_file})
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        return resp.json()['session_id']

    def df_preview(self, sid, instructions, *, up_to=None, row_limit=200):
        payload = {'session_id': sid, 'instructions': instructions, 'row_limit': row_limit}
        if up_to is not None:
            payload['up_to'] = up_to
        return self.client.post(reverse(PREVIEW_URL), payload, content_type='application/json')

    def import_preview(self, sid, instructions, mapping, *, row_limit=200):
        return self.client.post(
            reverse(IMPORT_PREVIEW_URL),
            {'session_id': sid, 'instructions': instructions, 'mapping': mapping, 'row_limit': row_limit},
            content_type='application/json',
        )

    def import_commit(self, sid, instructions, mapping):
        return self.client.post(
            reverse(IMPORT_COMMIT_URL),
            {'session_id': sid, 'instructions': instructions, 'mapping': mapping},
            content_type='application/json',
        )


# ---------------------------------------------------------------------------
# 1. Happy path — CSV
# ---------------------------------------------------------------------------
class HappyPathCSVTests(BaseImportTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_char_type('color', CharacteristicType.VALUE_STRING)
        make_char_type('weight', CharacteristicType.VALUE_INTEGER)

    def test_full_flow_csv_creates_products_categories_brands(self):
        sid = self.upload(csv_upload([
            DEFAULT_HEADER,
            ['S1', 'Дрель', 'Инструменты', 'Acme', 'red', '1500'],
            ['S2', 'Чехол', 'Аксессуары', 'Brandy', 'blue', '50'],
            ['S3', 'Молоток', 'Инструменты', 'Acme', 'silver', '900'],
        ]))

        # /dataframe/preview/ sees raw columns
        df_resp = self.df_preview(sid, csv_instructions())
        self.assertEqual(df_resp.status_code, 200)
        self.assertEqual(df_resp.json()['total_rows'], 3)
        self.assertEqual(df_resp.json()['columns'], DEFAULT_HEADER)

        # /products/import/preview/ produces 3 valid payloads
        prev = self.import_preview(sid, csv_instructions(), default_mapping())
        self.assertEqual(prev.status_code, 200, prev.content[:300])
        self.assertEqual(prev.json()['total'], 3)
        self.assertEqual(prev.json()['valid'], 3)
        self.assertEqual(prev.json()['rows'][0]['payload']['characteristics'], {'color': 'red', 'weight': 1500})

        # /products/import/commit/ persists
        commit = self.import_commit(sid, csv_instructions(), default_mapping())
        self.assertEqual(commit.status_code, 200, commit.content[:300])
        body = commit.json()
        self.assertEqual(body, {'created': 3, 'updated': 0, 'skipped': 0, 'errors': []})

        self.assertEqual(Product.objects.count(), 3)
        # Category/Brand resolved by name → get_or_create with deterministic slugs
        self.assertEqual(Category.objects.filter(name='Инструменты').count(), 1)
        self.assertEqual(Brand.objects.filter(name='Acme').count(), 1)
        p = Product.objects.get(sku='S1')
        self.assertEqual(p.characteristics, {'color': 'red', 'weight': 1500})
        self.assertEqual(p.status, 'active')
        self.assertEqual(p.category.slug, 'инструменты')  # allow_unicode=True
        self.assertEqual(p.brand.slug, 'acme')


# ---------------------------------------------------------------------------
# 2. Happy path — XLSX
# ---------------------------------------------------------------------------
class HappyPathXLSXTests(BaseImportTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_char_type('color', CharacteristicType.VALUE_STRING)
        make_char_type('weight', CharacteristicType.VALUE_INTEGER)

    def test_full_flow_xlsx_creates_products(self):
        sid = self.upload(xlsx_upload([
            DEFAULT_HEADER,
            ['X1', 'Шуруповёрт', 'Инструменты', 'Acme', 'black', '1200'],
            ['X2', 'Биты', 'Аксессуары', 'Acme', 'silver', '50'],
        ]))

        df_resp = self.df_preview(sid, xlsx_instructions(), row_limit=1)
        self.assertEqual(df_resp.status_code, 200)
        body = df_resp.json()
        self.assertEqual(body['total_rows'], 2)
        self.assertEqual(body['returned_rows'], 1)
        self.assertEqual(body['columns'], DEFAULT_HEADER)

        commit = self.import_commit(sid, xlsx_instructions(), default_mapping())
        self.assertEqual(commit.status_code, 200, commit.content[:300])
        self.assertEqual(commit.json()['created'], 2)
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(Product.objects.get(sku='X1').characteristics, {'color': 'black', 'weight': 1200})


# ---------------------------------------------------------------------------
# 3. Pipeline with transforms before mapping
# ---------------------------------------------------------------------------
class TransformPipelineTests(BaseImportTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_char_type('color', CharacteristicType.VALUE_STRING)

    def _instructions(self):
        return {
            'reader': {'func': 'read_csv', 'args': {}},
            'transforms': [
                {'func': 'select_columns', 'args': {'cols': 'art,title,cat,br,col'}},
                {'func': 'rename_columns', 'args': {
                    'mapping': 'art=sku\ntitle=name\ncat=category\nbr=brand\ncol=color',
                }},
                {'func': 'replace_values', 'args': {'column': 'color', 'mapping': 'красный=red'}},
            ],
        }

    def test_up_to_stops_pipeline_early(self):
        sid = self.upload(csv_upload([
            ['art', 'title', 'cat', 'br', 'col', 'trash', 'extra'],
            ['A1', 'Дрель', 'И', 'Acme', 'красный', 'x', 'y'],
        ]))
        resp = self.df_preview(sid, self._instructions(), up_to=1)
        self.assertEqual(resp.status_code, 200)
        # After only step 0 (select_columns), original raw column names remain (no rename yet)
        self.assertEqual(set(resp.json()['columns']), {'art', 'title', 'cat', 'br', 'col'})

    def test_full_pipeline_then_mapping_commits(self):
        sid = self.upload(csv_upload([
            ['art', 'title', 'cat', 'br', 'col', 'trash', 'extra'],
            ['A1', 'Дрель', 'И', 'Acme', 'красный', 'x', 'y'],
            ['A2', 'Молоток', 'И', 'Acme', 'красный', 'x', 'y'],
        ]))

        df_resp = self.df_preview(sid, self._instructions())
        self.assertEqual(df_resp.status_code, 200)
        cols = df_resp.json()['columns']
        self.assertEqual(set(cols), {'sku', 'name', 'category', 'brand', 'color'})

        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'category': {'column': 'category'},
            'brand': {'column': 'brand'},
            'characteristics': {'color': {'column': 'color'}},
        }
        commit = self.import_commit(sid, self._instructions(), mapping)
        self.assertEqual(commit.status_code, 200, commit.content[:300])
        self.assertEqual(commit.json()['created'], 2)
        # replace_values rewrote 'красный' → 'red'
        self.assertEqual(Product.objects.get(sku='A1').characteristics['color'], 'red')


# ---------------------------------------------------------------------------
# 4. CharacteristicType validation across all value types
# ---------------------------------------------------------------------------
class CharacteristicTypeTests(BaseImportTests):
    def _commit_one_row(self, char_value, char_def):
        """Helper: a single-row CSV importing one characteristic. Returns commit body."""
        ct = make_char_type('feat', **char_def)
        del ct  # not referenced further; created so apply_mapping can find it
        sid = self.upload(csv_upload([
            ['sku', 'name', 'feat'],
            ['F1', 'T', char_value],
        ]))
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'characteristics': {'feat': {'column': 'feat'}},
        }
        resp = self.import_commit(sid, csv_instructions(), mapping)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json()

    def test_string(self):
        body = self._commit_one_row('hello', {'value_type': CharacteristicType.VALUE_STRING})
        self.assertEqual(body['created'], 1)
        self.assertEqual(Product.objects.get(sku='F1').characteristics, {'feat': 'hello'})

    def test_integer(self):
        body = self._commit_one_row('42', {'value_type': CharacteristicType.VALUE_INTEGER})
        self.assertEqual(body['created'], 1)
        self.assertEqual(Product.objects.get(sku='F1').characteristics, {'feat': 42})

    def test_integer_rejects_non_numeric(self):
        body = self._commit_one_row('abc', {'value_type': CharacteristicType.VALUE_INTEGER})
        self.assertEqual(body['created'], 0)
        self.assertEqual(body['skipped'], 1)
        self.assertEqual(Product.objects.count(), 0)
        err = body['errors'][0]['errors']
        self.assertIn('characteristics.feat', err)

    def test_float(self):
        body = self._commit_one_row('3.14', {'value_type': CharacteristicType.VALUE_FLOAT})
        self.assertEqual(body['created'], 1)
        self.assertAlmostEqual(Product.objects.get(sku='F1').characteristics['feat'], 3.14)

    def test_boolean_truthy_values(self):
        for raw in ('1', 'true', 'да', 'yes', 'y'):
            Product.objects.all().delete()
            CharacteristicType.objects.filter(name='feat').delete()
            body = self._commit_one_row(raw, {'value_type': CharacteristicType.VALUE_BOOLEAN})
            self.assertEqual(body['created'], 1, f'value {raw!r} should commit')
            self.assertIs(Product.objects.get(sku='F1').characteristics['feat'], True, f'value {raw!r} → True')

    def test_boolean_falsy_values(self):
        for raw in ('0', 'false', 'нет', 'no', 'n'):
            Product.objects.all().delete()
            CharacteristicType.objects.filter(name='feat').delete()
            body = self._commit_one_row(raw, {'value_type': CharacteristicType.VALUE_BOOLEAN})
            self.assertEqual(body['created'], 1, f'value {raw!r} should commit')
            self.assertIs(Product.objects.get(sku='F1').characteristics['feat'], False, f'value {raw!r} → False')

    def test_boolean_rejects_garbage(self):
        body = self._commit_one_row('maybe', {'value_type': CharacteristicType.VALUE_BOOLEAN})
        self.assertEqual(body['skipped'], 1)
        self.assertEqual(Product.objects.count(), 0)

    def test_choice_ok(self):
        body = self._commit_one_row('M', {'value_type': CharacteristicType.VALUE_CHOICE, 'options': ['S', 'M', 'L']})
        self.assertEqual(body['created'], 1)
        self.assertEqual(Product.objects.get(sku='F1').characteristics['feat'], 'M')

    def test_choice_rejects_value_not_in_options(self):
        body = self._commit_one_row('XXL', {'value_type': CharacteristicType.VALUE_CHOICE, 'options': ['S', 'M', 'L']})
        self.assertEqual(body['skipped'], 1)
        self.assertEqual(Product.objects.count(), 0)

    def test_unknown_char_name_in_mapping_marks_row_invalid(self):
        """Mapping mentions a characteristic that doesn't exist in CharacteristicType."""
        sid = self.upload(csv_upload([
            ['sku', 'name', 'mystery'],
            ['F1', 'T', 'whatever'],
        ]))
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'characteristics': {'mystery': {'column': 'mystery'}},
        }
        resp = self.import_commit(sid, csv_instructions(), mapping)
        body = resp.json()
        self.assertEqual(body['created'], 0)
        self.assertEqual(body['skipped'], 1)
        self.assertIn('characteristics.mystery', body['errors'][0]['errors'])


# ---------------------------------------------------------------------------
# 5. Category & Brand resolution
# ---------------------------------------------------------------------------
class CategoryBrandResolutionTests(BaseImportTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_char_type('color', CharacteristicType.VALUE_STRING)
        make_char_type('weight', CharacteristicType.VALUE_INTEGER)

    def test_repeated_import_does_not_duplicate_category_or_brand(self):
        rows = [
            DEFAULT_HEADER,
            ['S1', 'A', 'Инструменты', 'Acme', 'red', '1'],
            ['S2', 'B', 'Инструменты', 'Acme', 'blue', '2'],
        ]
        sid1 = self.upload(csv_upload(rows))
        self.import_commit(sid1, csv_instructions(), default_mapping())
        sid2 = self.upload(csv_upload(rows + [['S3', 'C', 'Инструменты', 'Acme', 'green', '3']]))
        self.import_commit(sid2, csv_instructions(), default_mapping())

        self.assertEqual(Category.objects.filter(name='Инструменты').count(), 1)
        self.assertEqual(Brand.objects.filter(name='Acme').count(), 1)
        self.assertEqual(Product.objects.count(), 3)

    def test_cyrillic_brand_gets_unicode_slug(self):
        sid = self.upload(csv_upload([
            DEFAULT_HEADER,
            ['S1', 'A', 'C', 'Ромашка', 'red', '1'],
        ]))
        self.import_commit(sid, csv_instructions(), default_mapping())
        brand = Brand.objects.get(name='Ромашка')
        self.assertEqual(brand.slug, 'ромашка')

    def test_category_from_const_mapping(self):
        sid = self.upload(csv_upload([
            ['sku', 'name'],
            ['S1', 'A'],
        ]))
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'category': {'const': 'Стандарт'},
        }
        resp = self.import_commit(sid, csv_instructions(), mapping)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.assertEqual(resp.json()['created'], 1)
        self.assertTrue(Category.objects.filter(name='Стандарт').exists())


# ---------------------------------------------------------------------------
# 6. Upsert by SKU
# ---------------------------------------------------------------------------
class UpsertTests(BaseImportTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_char_type('color', CharacteristicType.VALUE_STRING)
        make_char_type('weight', CharacteristicType.VALUE_INTEGER)

    def test_commit_upserts_by_sku(self):
        sid1 = self.upload(csv_upload([
            DEFAULT_HEADER,
            ['S1', 'Дрель', 'Инструменты', 'Acme', 'red', '1500'],
        ]))
        self.import_commit(sid1, csv_instructions(), default_mapping())

        sid2 = self.upload(csv_upload([
            DEFAULT_HEADER,
            ['S1', 'Дрель PRO', 'Инструменты', 'Acme', 'blue', '1600'],
        ]))
        resp = self.import_commit(sid2, csv_instructions(), default_mapping())
        self.assertEqual(resp.json()['updated'], 1)
        self.assertEqual(Product.objects.count(), 1)
        p = Product.objects.get(sku='S1')
        self.assertEqual(p.name, 'Дрель PRO')
        self.assertEqual(p.characteristics, {'color': 'blue', 'weight': 1600})

    def test_upsert_replaces_characteristics_dict_entirely(self):
        """The second import's characteristics overwrite the first — old keys not in new mapping disappear."""
        sid1 = self.upload(csv_upload([
            DEFAULT_HEADER,
            ['S1', 'A', 'C', 'B', 'red', '100'],
        ]))
        self.import_commit(sid1, csv_instructions(), default_mapping())

        sid2 = self.upload(csv_upload([
            ['sku', 'name', 'category', 'brand', 'color'],
            ['S1', 'A', 'C', 'B', 'green'],
        ]))
        mapping = {
            'sku': {'column': 'sku'},
            'name': {'column': 'name'},
            'category': {'column': 'category'},
            'brand': {'column': 'brand'},
            'characteristics': {'color': {'column': 'color'}},
        }
        self.import_commit(sid2, csv_instructions(), mapping)
        p = Product.objects.get(sku='S1')
        self.assertEqual(p.characteristics, {'color': 'green'})  # weight gone


# ---------------------------------------------------------------------------
# 7. Error and edge cases
# ---------------------------------------------------------------------------
class ErrorCasesTests(BaseImportTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_char_type('color', CharacteristicType.VALUE_STRING)
        make_char_type('weight', CharacteristicType.VALUE_INTEGER)

    def test_session_not_found_returns_404(self):
        resp = self.import_preview('definitely-missing', csv_instructions(), default_mapping())
        self.assertEqual(resp.status_code, 404)
        commit = self.import_commit('definitely-missing', csv_instructions(), default_mapping())
        self.assertEqual(commit.status_code, 404)

    def test_unknown_transform_returns_400(self):
        sid = self.upload(csv_upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'r', '1']]))
        instructions = {
            'reader': {'func': 'read_csv', 'args': {}},
            'transforms': [{'func': 'no_such_transform', 'args': {}}],
        }
        resp = self.import_preview(sid, instructions, default_mapping())
        self.assertEqual(resp.status_code, 400, resp.content[:300])
        self.assertIn('error', resp.json())

    def test_unknown_reader_returns_400(self):
        sid = self.upload(csv_upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'r', '1']]))
        instructions = {'reader': {'func': 'no_such_reader', 'args': {}}, 'transforms': []}
        resp = self.import_commit(sid, instructions, default_mapping())
        self.assertEqual(resp.status_code, 400)

    def test_bad_xlsx_bytes_return_400(self):
        sid = self.upload(bytes_upload(b'this is not a real xlsx file', name='broken.xlsx'))
        resp = self.import_commit(sid, xlsx_instructions(), default_mapping())
        self.assertEqual(resp.status_code, 400, resp.content[:300])

    def test_missing_sku_row_skipped(self):
        sid = self.upload(csv_upload([
            DEFAULT_HEADER,
            ['S1', 'OK', 'C', 'B', 'red', '5'],
            ['', 'NoSku', 'C', 'B', 'red', '5'],
        ]))
        resp = self.import_commit(sid, csv_instructions(), default_mapping())
        body = resp.json()
        self.assertEqual(body['created'], 1)
        self.assertEqual(body['skipped'], 1)
        self.assertEqual(body['errors'][0]['errors'].get('sku'), 'SKU обязателен.')

    def test_missing_name_row_skipped(self):
        sid = self.upload(csv_upload([
            DEFAULT_HEADER,
            ['S1', '', 'C', 'B', 'red', '5'],
        ]))
        resp = self.import_commit(sid, csv_instructions(), default_mapping())
        body = resp.json()
        self.assertEqual(body['skipped'], 1)
        self.assertIn('name', body['errors'][0]['errors'])

    def test_row_limit_clamps_preview_output_but_not_total(self):
        rows = [DEFAULT_HEADER] + [
            [f'S{i}', f'N{i}', 'C', 'B', 'red', str(i)] for i in range(1, 11)
        ]
        sid = self.upload(csv_upload(rows))
        resp = self.import_preview(sid, csv_instructions(), default_mapping(), row_limit=3)
        body = resp.json()
        self.assertEqual(body['total'], 10)
        self.assertEqual(body['returned'], 3)
        self.assertEqual(len(body['rows']), 3)

    def test_invalid_mapping_field_shape_returns_400(self):
        sid = self.upload(csv_upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'r', '1']]))
        # ImportRequestSerializer requires mapping to be a DictField — empty serializer field still accepts
        # an empty dict, so to trigger 400 we send mapping as a list.
        resp = self.client.post(
            reverse(IMPORT_COMMIT_URL),
            {'session_id': sid, 'instructions': csv_instructions(), 'mapping': []},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_empty_mapping_commits_zero_with_errors(self):
        sid = self.upload(csv_upload([DEFAULT_HEADER, ['S1', 'A', 'C', 'B', 'r', '1']]))
        resp = self.import_commit(sid, csv_instructions(), {})
        body = resp.json()
        self.assertEqual(body['created'], 0)
        self.assertEqual(body['skipped'], 1)  # sku + name missing
