from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from product.models import Brand, Category, CharacteristicType, Product


@override_settings(SECURE_SSL_REDIRECT=False)
class ProductApiTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)


class AnonymousAccessTests(ProductApiTestBase):
    def test_anonymous_blocked(self):
        self.client.logout()
        resp = self.client.get(reverse('product_api:product-list'))
        self.assertEqual(resp.status_code, 401)


class CategoryCrudTests(ProductApiTestBase):
    def test_create_list_update_delete(self):
        resp = self.client.post(
            reverse('product_api:category-list'),
            {'name': 'Электроника'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        pk = resp.json()['id']

        list_resp = self.client.get(reverse('product_api:category-list'))
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json()), 1)

        upd = self.client.patch(
            reverse('product_api:category-detail', args=[pk]),
            {'name': 'Электроника и техника'},
            content_type='application/json',
        )
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.json()['name'], 'Электроника и техника')

        d = self.client.delete(reverse('product_api:category-detail', args=[pk]))
        self.assertEqual(d.status_code, 204)


class BrandCrudTests(ProductApiTestBase):
    def test_create_brand(self):
        resp = self.client.post(
            reverse('product_api:brand-list'),
            {'name': 'Acme'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Brand.objects.count(), 1)


class CharacteristicTypeCrudTests(ProductApiTestBase):
    def test_create_and_filter_by_category(self):
        cat = Category.objects.create(name='Электроника')
        resp = self.client.post(
            reverse('product_api:characteristic-type-list'),
            {
                'name': 'voltage', 'label': 'Напряжение',
                'value_type': 'float', 'unit': 'В',
                'categories': [cat.id],
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])

        filtered = self.client.get(
            reverse('product_api:characteristic-type-list') + f'?category={cat.id}'
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(len(filtered.json()), 1)


class ProductCrudTests(ProductApiTestBase):
    def test_create_product_with_characteristics(self):
        CharacteristicType.objects.create(name='color', label='Цвет', value_type='string')
        CharacteristicType.objects.create(name='weight', label='Вес', value_type='integer')

        resp = self.client.post(
            reverse('product_api:product-list'),
            {
                'sku': 'SKU-1', 'name': 'Дрель',
                'characteristics': {'color': 'red', 'weight': '3'},
                'status': 'active',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['characteristics'], {'color': 'red', 'weight': 3})

    def test_create_product_rejects_unknown_characteristic(self):
        resp = self.client.post(
            reverse('product_api:product-list'),
            {'sku': 'SKU-2', 'name': 'X', 'characteristics': {'unknown_char': 1}},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
