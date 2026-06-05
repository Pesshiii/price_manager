"""Tests for category characteristics management endpoints.

POST   /api/products/categories/<id>/characteristics/        — add existing or create new
DELETE /api/products/categories/<id>/characteristics/<cid>/  — remove from M2M
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from product.models import Category, CharacteristicType


@override_settings(SECURE_SSL_REDIRECT=False)
class CategoryCharacteristicsTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = Category.objects.create(name='Электроника')
        cls.ct = CharacteristicType.objects.create(
            name='color', label='Цвет', value_type='string'
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _add_url(self):
        return f'/api/products/categories/{self.cat.id}/characteristics/'

    def _remove_url(self, char_id):
        return f'/api/products/categories/{self.cat.id}/characteristics/{char_id}/'

    def _post(self, data):
        return self.client.post(self._add_url(), data, content_type='application/json')

    def _delete(self, char_id):
        return self.client.delete(self._remove_url(char_id))


class AddCharacteristicTests(CategoryCharacteristicsTestBase):
    def test_add_existing_by_char_type_id(self):
        resp = self._post({'char_type_id': self.ct.id})
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.assertEqual(resp.json()['id'], self.ct.id)
        self.assertTrue(self.cat.characteristic_types.filter(pk=self.ct.pk).exists())

    def test_add_already_linked_is_idempotent(self):
        self.cat.characteristic_types.add(self.ct)
        resp = self._post({'char_type_id': self.ct.id})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(self.cat.characteristic_types.filter(pk=self.ct.pk).count(), 1)

    def test_add_nonexistent_char_type_id_returns_404(self):
        resp = self._post({'char_type_id': 99999})
        self.assertEqual(resp.status_code, 404)

    def test_inline_create_new_char_type(self):
        resp = self._post({
            'create': {'name': 'weight', 'label': 'Вес', 'value_type': 'integer'}
        })
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        ct = CharacteristicType.objects.get(name='weight')
        self.assertEqual(resp.json()['id'], ct.id)
        self.assertTrue(self.cat.characteristic_types.filter(pk=ct.pk).exists())

    def test_inline_create_name_collision_returns_400(self):
        # 'color' already exists from setUpTestData
        resp = self._post({
            'create': {'name': 'color', 'label': 'Дубль', 'value_type': 'string'}
        })
        self.assertEqual(resp.status_code, 400)

    def test_missing_both_fields_returns_400(self):
        resp = self._post({'foo': 'bar'})
        self.assertEqual(resp.status_code, 400)


class RemoveCharacteristicTests(CategoryCharacteristicsTestBase):
    def test_remove_linked_char(self):
        self.cat.characteristic_types.add(self.ct)
        resp = self._delete(self.ct.id)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(self.cat.characteristic_types.filter(pk=self.ct.pk).exists())

    def test_remove_not_linked_returns_404(self):
        # ct is NOT linked to cat
        resp = self._delete(self.ct.id)
        self.assertEqual(resp.status_code, 404)

    def test_remove_nonexistent_char_type_returns_404(self):
        resp = self._delete(99999)
        self.assertEqual(resp.status_code, 404)
