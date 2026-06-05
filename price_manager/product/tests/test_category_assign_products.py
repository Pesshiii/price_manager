"""Tests for bulk product assignment and unassigned product pool filter.

POST /api/products/categories/<id>/assign-products/
     {product_ids: [...]} → {assigned: N}

GET  /api/products/products/?category__isnull=true
     → only products with category IS NULL
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from product.models import Category, Product


@override_settings(SECURE_SSL_REDIRECT=False)
class AssignProductsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = Category.objects.create(name='Электроника')
        cls.other_cat = Category.objects.create(name='Другая')

    def setUp(self):
        self.client.force_login(self.user)

    def _assign_url(self):
        return f'/api/products/categories/{self.cat.id}/assign-products/'

    def _assign(self, product_ids):
        return self.client.post(
            self._assign_url(),
            {'product_ids': product_ids},
            content_type='application/json',
        )

    def test_assigns_unassigned_products(self):
        p1 = Product.objects.create(sku='P1', name='A', category=None)
        p2 = Product.objects.create(sku='P2', name='B', category=None)
        resp = self._assign([p1.id, p2.id])
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.assertEqual(resp.json()['assigned'], 2)
        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(p1.category, self.cat)
        self.assertEqual(p2.category, self.cat)

    def test_skips_already_assigned_products(self):
        p_free = Product.objects.create(sku='P3', name='C', category=None)
        p_taken = Product.objects.create(sku='P4', name='D', category=self.other_cat)
        resp = self._assign([p_free.id, p_taken.id])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['assigned'], 1)
        p_taken.refresh_from_db()
        self.assertEqual(p_taken.category, self.other_cat)

    def test_empty_list_returns_zero(self):
        resp = self._assign([])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['assigned'], 0)

    def test_nonexistent_ids_are_ignored(self):
        p = Product.objects.create(sku='P5', name='E', category=None)
        resp = self._assign([p.id, 99999, 88888])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['assigned'], 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class CategoryIsnullFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = Category.objects.create(name='Электроника')

    def setUp(self):
        self.client.force_login(self.user)

    def test_category_isnull_true_returns_unassigned(self):
        Product.objects.create(sku='PF', name='Free', category=None)
        Product.objects.create(sku='PA', name='Assigned', category=self.cat)
        resp = self.client.get('/api/products/products/?category__isnull=true')
        self.assertEqual(resp.status_code, 200)
        skus = {row['sku'] for row in resp.json()['results']}
        self.assertIn('PF', skus)
        self.assertNotIn('PA', skus)

    def test_category_isnull_false_returns_assigned(self):
        Product.objects.create(sku='PF2', name='Free2', category=None)
        Product.objects.create(sku='PA2', name='Assigned2', category=self.cat)
        resp = self.client.get('/api/products/products/?category__isnull=false')
        self.assertEqual(resp.status_code, 200)
        skus = {row['sku'] for row in resp.json()['results']}
        self.assertNotIn('PF2', skus)
        self.assertIn('PA2', skus)
