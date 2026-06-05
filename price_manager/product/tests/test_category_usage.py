"""Tests for category characteristic usage count endpoint.

GET /api/products/categories/<id>/characteristics/<cid>/usage/
    → {count: N}  — products in THIS category with non-null value for the char
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from product.models import Category, CharacteristicType, Product


@override_settings(SECURE_SSL_REDIRECT=False)
class CategoryUsageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = Category.objects.create(name='Электроника')
        cls.other_cat = Category.objects.create(name='Другая')
        cls.ct = CharacteristicType.objects.create(name='color', label='Цвет', value_type='string')
        cls.cat.characteristic_types.add(cls.ct)

    def setUp(self):
        self.client.force_login(self.user)

    def _url(self):
        return f'/api/products/categories/{self.cat.id}/characteristics/{self.ct.id}/usage/'

    def test_counts_products_with_value_set(self):
        Product.objects.create(sku='P1', name='A', category=self.cat, characteristics={'color': 'red'})
        Product.objects.create(sku='P2', name='B', category=self.cat, characteristics={'color': 'blue'})
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 2)

    def test_excludes_products_without_char_key(self):
        Product.objects.create(sku='P3', name='C', category=self.cat, characteristics={})
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 0)

    def test_excludes_products_in_other_category(self):
        Product.objects.create(
            sku='P4', name='D', category=self.other_cat, characteristics={'color': 'green'}
        )
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 0)

    def test_excludes_products_with_null_value(self):
        # JSON null stored in characteristics should NOT be counted
        Product.objects.create(
            sku='P5', name='E', category=self.cat, characteristics={'color': None}
        )
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 0)

    def test_nonexistent_char_type_returns_404(self):
        url = f'/api/products/categories/{self.cat.id}/characteristics/99999/usage/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
