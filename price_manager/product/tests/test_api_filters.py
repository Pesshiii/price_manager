from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from product.models import Brand, Category, CharacteristicType, Product


@override_settings(SECURE_SSL_REDIRECT=False)
class ProductFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

        cls.electronics = Category.objects.create(name='Электроника')
        cls.phones = Category.objects.create(name='Телефоны', parent=cls.electronics)
        cls.tools = Category.objects.create(name='Инструменты')

        cls.acme = Brand.objects.create(name='Acme')

        CharacteristicType.objects.create(name='color', label='Цвет', value_type='string')
        CharacteristicType.objects.create(name='weight', label='Вес', value_type='integer')

        cls.p1 = Product.objects.create(
            sku='P1', name='Смартфон', category=cls.phones, brand=cls.acme,
            characteristics={'color': 'red', 'weight': 200}, status='active',
        )
        cls.p2 = Product.objects.create(
            sku='P2', name='Дрель', category=cls.tools,
            characteristics={'color': 'blue', 'weight': 1500}, status='active',
        )
        cls.p3 = Product.objects.create(
            sku='P3', name='Чехол', category=cls.phones,
            characteristics={'color': 'red'}, status='draft',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _list(self, query):
        resp = self.client.get(reverse('product_api:product-list') + query)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json()

    def test_category_includes_descendants(self):
        body = self._list(f'?category={self.electronics.id}')
        skus = {row['sku'] for row in body['results']}
        self.assertEqual(skus, {'P1', 'P3'})

    def test_brand_filter(self):
        body = self._list(f'?brand={self.acme.id}')
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['results'][0]['sku'], 'P1')

    def test_status_filter(self):
        body = self._list('?status=draft')
        self.assertEqual({row['sku'] for row in body['results']}, {'P3'})

    def test_q_search(self):
        body = self._list('?q=дрель')
        self.assertEqual({row['sku'] for row in body['results']}, {'P2'})

    def test_characteristic_filter_string(self):
        body = self._list('?char__color=red')
        self.assertEqual({row['sku'] for row in body['results']}, {'P1', 'P3'})

    def test_characteristic_filter_integer(self):
        body = self._list('?char__weight=200')
        self.assertEqual({row['sku'] for row in body['results']}, {'P1'})

    def test_combined_filters(self):
        body = self._list(f'?category={self.electronics.id}&char__color=red&status=active')
        self.assertEqual({row['sku'] for row in body['results']}, {'P1'})


@override_settings(SECURE_SSL_REDIRECT=False)
class ProductFacetsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        CharacteristicType.objects.create(name='color', label='Цвет', value_type='string')

        Product.objects.create(sku='A', name='a', characteristics={'color': 'red'})
        Product.objects.create(sku='B', name='b', characteristics={'color': 'red'})
        Product.objects.create(sku='C', name='c', characteristics={'color': 'blue'})

    def setUp(self):
        self.client.force_login(self.user)

    def test_facets_shape(self):
        resp = self.client.get(reverse('product_api:product-facets'))
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertIn('color', body)
        counts = {item['value']: item['count'] for item in body['color']}
        self.assertEqual(counts, {'red': 2, 'blue': 1})
