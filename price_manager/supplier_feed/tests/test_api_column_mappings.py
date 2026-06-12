"""Tests for FeedColumnMapping CRUD API."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from pricing.models import PriceType
from supplier_feed.models import FeedColumnMapping
from .fixtures import make_feed_mapping, make_supplier

CM_LIST = 'supplier_feed_api:feedcolumnmapping-list'
CM_DETAIL = 'supplier_feed_api:feedcolumnmapping-detail'


def make_price_type(name='розница', label='Розничная цена'):
    pt, _ = PriceType.objects.get_or_create(name=name, defaults={'label': label})
    return pt


@override_settings(SECURE_SSL_REDIRECT=False)
class ColumnMappingApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.supplier = make_supplier()
        cls.mapping = make_feed_mapping(supplier=cls.supplier)

    def setUp(self):
        self.client.force_login(self.user)


class CreateColumnMappingTests(ColumnMappingApiBase):
    def test_create_role_price_with_price_type_returns_201(self):
        pt = make_price_type()
        resp = self.client.post(
            reverse(CM_LIST),
            {
                'feed_mapping': self.mapping.pk,
                'column_name': 'price',
                'role': 'price',
                'price_type': pt.pk,
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['column_name'], 'price')
        self.assertEqual(data['role'], 'price')
        self.assertEqual(data['price_type'], pt.pk)

    def test_create_role_stock_returns_201(self):
        resp = self.client.post(
            reverse(CM_LIST),
            {
                'feed_mapping': self.mapping.pk,
                'column_name': 'stock',
                'role': 'stock',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['role'], 'stock')
        self.assertIsNone(data['price_type'])

    def test_create_role_other_returns_201(self):
        resp = self.client.post(
            reverse(CM_LIST),
            {
                'feed_mapping': self.mapping.pk,
                'column_name': 'description',
                'role': 'other',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.assertEqual(resp.json()['role'], 'other')

    def test_list_filtered_by_feed_mapping(self):
        other_mapping = make_feed_mapping(supplier=self.supplier, name='Другой')
        FeedColumnMapping.objects.create(
            feed_mapping=self.mapping, column_name='price', role='stock'
        )
        FeedColumnMapping.objects.create(
            feed_mapping=other_mapping, column_name='cost', role='stock'
        )

        resp = self.client.get(reverse(CM_LIST) + f'?feed_mapping={self.mapping.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]['column_name'], 'price')

    def test_price_type_required_when_role_price_returns_400(self):
        resp = self.client.post(
            reverse(CM_LIST),
            {
                'feed_mapping': self.mapping.pk,
                'column_name': 'price',
                'role': 'price',
                # price_type intentionally omitted
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('price_type', resp.json())

    def test_duplicate_feed_mapping_column_name_returns_400(self):
        FeedColumnMapping.objects.create(
            feed_mapping=self.mapping, column_name='qty', role='stock'
        )
        resp = self.client.post(
            reverse(CM_LIST),
            {
                'feed_mapping': self.mapping.pk,
                'column_name': 'qty',
                'role': 'other',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_anonymous_gets_401(self):
        self.client.logout()
        resp = self.client.get(reverse(CM_LIST))
        self.assertEqual(resp.status_code, 401)


class UpdateDeleteColumnMappingTests(ColumnMappingApiBase):
    def setUp(self):
        super().setUp()
        self.pt = make_price_type()
        self.cm = FeedColumnMapping.objects.create(
            feed_mapping=self.mapping,
            column_name='price',
            role='price',
            price_type=self.pt,
        )

    def test_retrieve_returns_200(self):
        resp = self.client.get(reverse(CM_DETAIL, args=[self.cm.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['column_name'], 'price')

    def test_patch_role_returns_200(self):
        resp = self.client.patch(
            reverse(CM_DETAIL, args=[self.cm.pk]),
            {'role': 'other', 'price_type': None},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['role'], 'other')

    def test_patch_price_type_null_on_price_role_returns_400(self):
        """PATCH that clears price_type on a price-role record must be rejected."""
        resp = self.client.patch(
            reverse(CM_DETAIL, args=[self.cm.pk]),
            {'price_type': None},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400, resp.content[:300])
        self.assertIn('price_type', resp.json())

    def test_delete_returns_204(self):
        resp = self.client.delete(reverse(CM_DETAIL, args=[self.cm.pk]))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(FeedColumnMapping.objects.filter(pk=self.cm.pk).exists())
