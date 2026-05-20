"""CRUD tests for CharacteristicType — filters, detail view, and the inline-update
guard that blocks ``name`` / ``value_type`` changes (those go through async
retype/rename endpoints; see ``test_char_mutation.py``)."""
from __future__ import annotations

from django.urls import reverse

from product.models import Category, CharacteristicType

from .fixtures import make_char_type
from .test_api_crud import ProductApiTestBase


class CharacteristicTypeListFilterTests(ProductApiTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat_a = Category.objects.create(name='Электроника')
        cls.cat_b = Category.objects.create(name='Инструменты')
        cls.color = make_char_type('color', CharacteristicType.VALUE_STRING, label='Цвет')
        cls.color.categories.set([cls.cat_a, cls.cat_b])
        cls.weight = make_char_type(
            'weight', CharacteristicType.VALUE_INTEGER, label='Вес', required=True,
        )
        cls.weight.categories.set([cls.cat_b])
        cls.voltage = make_char_type(
            'voltage', CharacteristicType.VALUE_FLOAT, label='Напряжение',
        )
        cls.voltage.categories.set([cls.cat_a])

    def _list(self, qs=''):
        return self.client.get(
            reverse('product_api:characteristic-type-list') + (f'?{qs}' if qs else '')
        )

    def test_unfiltered_returns_all(self):
        resp = self._list()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 3)

    def test_search_filter_matches_name_and_label(self):
        # icontains hits both fields — label 'Цвет' for one, name 'color' for the same row.
        resp = self._list('search=Цвет')
        self.assertEqual(resp.json()['count'], 1)
        self.assertEqual(resp.json()['results'][0]['name'], 'color')

    def test_category_filter_single(self):
        resp = self._list(f'category={self.cat_b.id}')
        names = {r['name'] for r in resp.json()['results']}
        self.assertEqual(names, {'color', 'weight'})

    def test_category_filter_multi_unions_via_distinct(self):
        # color belongs to both cats. Without distinct() it would appear twice.
        resp = self._list(f'category={self.cat_a.id}&category={self.cat_b.id}')
        names = [r['name'] for r in resp.json()['results']]
        self.assertEqual(sorted(names), ['color', 'voltage', 'weight'])
        self.assertEqual(len(names), 3)  # no dup

    def test_value_type_filter(self):
        resp = self._list('value_type=integer')
        self.assertEqual(resp.json()['count'], 1)
        self.assertEqual(resp.json()['results'][0]['name'], 'weight')

    def test_required_filter_true(self):
        resp = self._list('required=true')
        self.assertEqual(resp.json()['count'], 1)
        self.assertEqual(resp.json()['results'][0]['name'], 'weight')

    def test_required_filter_false(self):
        resp = self._list('required=false')
        self.assertEqual(resp.json()['count'], 2)

    def test_filters_can_compose(self):
        resp = self._list(f'category={self.cat_a.id}&value_type=string')
        self.assertEqual(resp.json()['count'], 1)
        self.assertEqual(resp.json()['results'][0]['name'], 'color')


class CharacteristicTypeDetailTests(ProductApiTestBase):
    def test_retrieve_includes_categories_detail(self):
        cat = Category.objects.create(name='Электроника')
        ct = make_char_type('voltage', CharacteristicType.VALUE_FLOAT)
        ct.categories.set([cat])

        resp = self.client.get(
            reverse('product_api:characteristic-type-detail', args=[ct.id])
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['categories'], [cat.id])
        self.assertEqual(len(body['categories_detail']), 1)
        self.assertEqual(body['categories_detail'][0]['name'], 'Электроника')
        # `level` comes from MPTT — included for hierarchical rendering.
        self.assertIn('level', body['categories_detail'][0])


class CharacteristicTypeInlineUpdateGuardTests(ProductApiTestBase):
    """PATCH must reject ``name`` / ``value_type`` changes — they require a
    JSONB migration via the dedicated retype/rename endpoints."""

    def setUp(self):
        super().setUp()
        self.ct = make_char_type('weight', CharacteristicType.VALUE_INTEGER, label='Вес')

    def _patch(self, body):
        return self.client.patch(
            reverse('product_api:characteristic-type-detail', args=[self.ct.id]),
            body,
            content_type='application/json',
        )

    def test_patch_label_only_works(self):
        resp = self._patch({'label': 'Масса'})
        self.assertEqual(resp.status_code, 200)
        self.ct.refresh_from_db()
        self.assertEqual(self.ct.label, 'Масса')

    def test_patch_unit_only_works(self):
        resp = self._patch({'unit': 'кг'})
        self.assertEqual(resp.status_code, 200)
        self.ct.refresh_from_db()
        self.assertEqual(self.ct.unit, 'кг')

    def test_patch_name_change_is_blocked(self):
        resp = self._patch({'name': 'mass'})
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn('name', body)
        self.assertIn('rename/commit', body['name'][0] if isinstance(body['name'], list) else body['name'])
        self.ct.refresh_from_db()
        self.assertEqual(self.ct.name, 'weight')

    def test_patch_value_type_change_is_blocked(self):
        resp = self._patch({'value_type': 'float'})
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn('value_type', body)
        self.assertIn('retype/commit', body['value_type'][0] if isinstance(body['value_type'], list) else body['value_type'])
        self.ct.refresh_from_db()
        self.assertEqual(self.ct.value_type, 'integer')

    def test_patch_same_name_is_idempotent(self):
        # Sending the same name back should not trigger the guard.
        resp = self._patch({'name': 'weight'})
        self.assertEqual(resp.status_code, 200)

    def test_delete_removes_type(self):
        resp = self.client.delete(
            reverse('product_api:characteristic-type-detail', args=[self.ct.id])
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(CharacteristicType.objects.filter(pk=self.ct.id).exists())
