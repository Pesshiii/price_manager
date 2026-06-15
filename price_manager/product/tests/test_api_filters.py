from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from pricing.models import PriceType, ProductPrice
from product.models import Brand, Category, CharacteristicType, Product
from supplier.models import Supplier


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
        # Self-describing shape: {label, unit, value_type, buckets}
        self.assertIn('label', body['color'])
        self.assertIn('buckets', body['color'])
        counts = {item['value']: item['count'] for item in body['color']['buckets']}
        self.assertEqual(counts, {'red': 2, 'blue': 1})


@override_settings(SECURE_SSL_REDIRECT=False)
class ProductPriceAnnotationFilterTests(TestCase):
    """Tests for ?price_types= annotation and ?price_type=/price_min/price_max filters."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='price_user', password='p')

        cls.retail_type = PriceType.objects.create(name='retail', label='Розничная')
        cls.wholesale_type = PriceType.objects.create(name='wholesale', label='Оптовая')

        cls.supplier1 = Supplier.objects.create(name='Поставщик 1')
        cls.supplier2 = Supplier.objects.create(name='Поставщик 2')

        cls.p1 = Product.objects.create(sku='PR1', name='Товар 1')
        cls.p2 = Product.objects.create(sku='PR2', name='Товар 2')

        # p1 has two retail prices from different suppliers — min is 800
        ProductPrice.objects.create(
            product=cls.p1, supplier=cls.supplier1,
            price_type=cls.retail_type, value='1200.00',
        )
        ProductPrice.objects.create(
            product=cls.p1, supplier=cls.supplier2,
            price_type=cls.retail_type, value='800.00',
        )
        # p1 also has a wholesale price
        ProductPrice.objects.create(
            product=cls.p1, supplier=cls.supplier1,
            price_type=cls.wholesale_type, value='700.00',
        )
        # p2 has no prices at all

    def setUp(self):
        self.client.force_login(self.user)

    def _list(self, query):
        resp = self.client.get(reverse('product_api:product-list') + query)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json()

    def _result_by_sku(self, body, sku):
        for row in body['results']:
            if row['sku'] == sku:
                return row
        return None

    def test_price_types_annotation_returns_min(self):
        """?price_types=retail returns minimum price across suppliers."""
        body = self._list('?price_types=retail')
        row = self._result_by_sku(body, 'PR1')
        self.assertIsNotNone(row)
        self.assertIn('prices', row)
        self.assertIn('retail', row['prices'])
        self.assertEqual(row['prices']['retail'], 800.0)

    def test_price_types_annotation_null_for_missing(self):
        """?price_types=retail returns null for a product with no prices."""
        body = self._list('?price_types=retail')
        row = self._result_by_sku(body, 'PR2')
        self.assertIsNotNone(row)
        self.assertIn('prices', row)
        self.assertIsNone(row['prices']['retail'])

    def test_price_types_multiple_slugs(self):
        """?price_types=retail&price_types=wholesale annotates both types."""
        body = self._list('?price_types=retail&price_types=wholesale')
        row = self._result_by_sku(body, 'PR1')
        self.assertIsNotNone(row)
        self.assertEqual(row['prices']['retail'], 800.0)
        self.assertEqual(row['prices']['wholesale'], 700.0)

    def test_price_type_filter_by_min(self):
        """?price_type=retail&price_min=1000 excludes p1 whose min retail is 800."""
        body = self._list('?price_type=retail&price_min=1000')
        skus = {row['sku'] for row in body['results']}
        # p1 has a retail price of 800 (below 1000) AND 1200 (above 1000).
        # Exists() returns True if ANY price matches, so p1 should be included.
        self.assertIn('PR1', skus)
        # p2 has no retail prices → excluded
        self.assertNotIn('PR2', skus)

    def test_price_type_filter_max(self):
        """?price_type=retail&price_max=500 excludes products with no retail price <= 500."""
        body = self._list('?price_type=retail&price_max=500')
        skus = {row['sku'] for row in body['results']}
        # Neither p1 (min 800) nor p2 (no price) qualifies
        self.assertNotIn('PR1', skus)
        self.assertNotIn('PR2', skus)

    def test_price_type_filter_includes_match(self):
        """?price_type=retail&price_max=900 includes p1 which has a price of 800."""
        body = self._list('?price_type=retail&price_max=900')
        skus = {row['sku'] for row in body['results']}
        self.assertIn('PR1', skus)

    def test_no_price_types_param_no_prices_field(self):
        """Without ?price_types param, prices key is absent from the response."""
        body = self._list('')
        for row in body['results']:
            self.assertNotIn('prices', row)

    def test_invalid_price_min_returns_empty(self):
        """?price_type=retail&price_min=abc returns no results (invalid decimal)."""
        body = self._list('?price_type=retail&price_min=abc')
        self.assertEqual(body['count'], 0)

    def test_invalid_price_max_returns_empty(self):
        """?price_type=retail&price_max=xyz returns no results (invalid decimal)."""
        body = self._list('?price_type=retail&price_max=xyz')
        self.assertEqual(body['count'], 0)
