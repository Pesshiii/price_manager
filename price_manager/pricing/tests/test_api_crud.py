from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from pricing.models import PriceType, PricingRule
from .fixtures import make_price_type, make_supplier


@override_settings(SECURE_SSL_REDIRECT=False)
class PricingApiTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)


class AnonymousAccessTests(PricingApiTestBase):
    def test_price_types_blocked_for_anonymous(self):
        self.client.logout()
        resp = self.client.get(reverse('pricing_api:price-type-list'))
        self.assertEqual(resp.status_code, 401)

    def test_rules_blocked_for_anonymous(self):
        self.client.logout()
        resp = self.client.get(reverse('pricing_api:pricing-rule-list'))
        self.assertEqual(resp.status_code, 401)


class PriceTypeCrudTests(PricingApiTestBase):
    def test_create_list_update_delete(self):
        resp = self.client.post(
            reverse('pricing_api:price-type-list'),
            {'name': 'закупочная', 'label': 'Закупочная цена'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        pk = resp.json()['id']

        list_resp = self.client.get(reverse('pricing_api:price-type-list'))
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.json()['count'], 1)

        upd = self.client.patch(
            reverse('pricing_api:price-type-detail', args=[pk]),
            {'label': 'Закупочная'},
            content_type='application/json',
        )
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.json()['label'], 'Закупочная')

        d = self.client.delete(reverse('pricing_api:price-type-detail', args=[pk]))
        self.assertEqual(d.status_code, 204)
        self.assertEqual(PriceType.objects.count(), 0)

    def test_search_filter(self):
        make_price_type(name='закупочная', label='Закупочная')
        make_price_type(name='розничная', label='Розничная')

        resp = self.client.get(reverse('pricing_api:price-type-list') + '?search=закуп')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 1)
        self.assertEqual(resp.json()['results'][0]['name'], 'закупочная')


class PricingRuleCrudTests(PricingApiTestBase):
    def setUp(self):
        super().setUp()
        self.supplier = make_supplier()
        self.src_pt = make_price_type(name='закупочная', label='Закупочная')
        self.dest_pt = make_price_type(name='розничная', label='Розничная')

    def test_create_and_list(self):
        payload = {
            'supplier': self.supplier.pk,
            'source_price_type': self.src_pt.pk,
            'dest_price_type': self.dest_pt.pk,
            'mode': 'formula',
            'params': {'markup': 20, 'increase': 0},
            'priority': 0,
        }
        resp = self.client.post(
            reverse('pricing_api:pricing-rule-list'),
            payload,
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.assertEqual(PricingRule.objects.count(), 1)

    def test_filter_by_supplier(self):
        supplier2 = make_supplier(name='Other Supplier')
        PricingRule.objects.create(
            supplier=self.supplier,
            source_price_type=self.src_pt,
            dest_price_type=self.dest_pt,
            mode='fixed',
            params={'value': 100},
        )
        PricingRule.objects.create(
            supplier=supplier2,
            source_price_type=self.src_pt,
            dest_price_type=self.dest_pt,
            mode='fixed',
            params={'value': 200},
        )

        resp = self.client.get(
            reverse('pricing_api:pricing-rule-list') + f'?supplier={self.supplier.pk}'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 1)
        self.assertEqual(resp.json()['results'][0]['supplier'], self.supplier.pk)

    def test_delete(self):
        rule = PricingRule.objects.create(
            supplier=self.supplier,
            source_price_type=self.src_pt,
            dest_price_type=self.dest_pt,
            mode='fixed',
            params={'value': 50},
        )
        resp = self.client.delete(reverse('pricing_api:pricing-rule-detail', args=[rule.pk]))
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(PricingRule.objects.count(), 0)
