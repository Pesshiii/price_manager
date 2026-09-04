from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier.models import Supplier


@override_settings(SECURE_SSL_REDIRECT=False)
class SupplierApiTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)


class AnonymousAccessTests(SupplierApiTestBase):
    def test_anonymous_blocked(self):
        self.client.logout()
        resp = self.client.get(reverse('supplier_api:supplier-list'))
        self.assertEqual(resp.status_code, 401)


class SupplierCrudTests(SupplierApiTestBase):
    def test_create(self):
        resp = self.client.post(
            reverse('supplier_api:supplier-list'),
            {'name': 'Рога и Копыта'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.assertEqual(resp.json()['name'], 'Рога и Копыта')
        self.assertEqual(Supplier.objects.count(), 1)

    def test_retrieve(self):
        supplier = Supplier.objects.create(name='Альфа')
        resp = self.client.get(
            reverse('supplier_api:supplier-detail', args=[supplier.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Альфа')

    def test_update(self):
        supplier = Supplier.objects.create(name='Альфа')
        resp = self.client.patch(
            reverse('supplier_api:supplier-detail', args=[supplier.pk]),
            {'name': 'Альфа Плюс'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Альфа Плюс')
        supplier.refresh_from_db()
        self.assertEqual(supplier.name, 'Альфа Плюс')

    def test_delete(self):
        supplier = Supplier.objects.create(name='Альфа')
        resp = self.client.delete(
            reverse('supplier_api:supplier-detail', args=[supplier.pk])
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Supplier.objects.filter(pk=supplier.pk).exists())

    def test_duplicate_name_rejected(self):
        Supplier.objects.create(name='Альфа')
        resp = self.client.post(
            reverse('supplier_api:supplier-list'),
            {'name': 'Альфа'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
