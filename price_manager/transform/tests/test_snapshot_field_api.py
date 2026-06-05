from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(SECURE_SSL_REDIRECT=False)
class SnapshotFieldApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)

    def _list(self):
        return self.client.get(reverse('transform_api:snapshotfield-list'))

    def _create(self, **kwargs):
        payload = {'slug': 'price', 'name': 'Цена', 'value_type': 'number'}
        payload.update(kwargs)
        return self.client.post(
            reverse('transform_api:snapshotfield-list'),
            payload,
            content_type='application/json',
        )

    def _detail(self, pk):
        return self.client.get(reverse('transform_api:snapshotfield-detail', args=[pk]))


# --- Cycle 1: tracer bullet -------------------------------------------------

class ListEndpointTest(SnapshotFieldApiBase):
    def test_list_returns_200_empty(self):
        resp = self._list()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['results'], [])


# --- Cycle 2: create --------------------------------------------------------

class CreateSnapshotFieldTest(SnapshotFieldApiBase):
    def test_create_returns_201(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['slug'], 'price')
        self.assertEqual(body['name'], 'Цена')
        self.assertEqual(body['value_type'], 'number')
        self.assertIsNone(body['description'])

    def test_description_optional(self):
        resp = self._create(slug='weight', name='Вес', value_type='number')
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()['description'])

    def test_create_with_description(self):
        resp = self._create(description='Розничная цена товара')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['description'], 'Розничная цена товара')


# --- Cycle 3: slug uniqueness -----------------------------------------------

class SlugUniquenessTest(SnapshotFieldApiBase):
    def test_duplicate_slug_returns_400(self):
        self._create(slug='price', name='Цена', value_type='number')
        resp = self._create(slug='price', name='Другое', value_type='string')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('slug', resp.json())


# --- Cycle 4: value_type validation -----------------------------------------

class ValueTypeValidationTest(SnapshotFieldApiBase):
    def test_invalid_value_type_returns_400(self):
        resp = self._create(value_type='integer')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('value_type', resp.json())

    def test_all_valid_value_types(self):
        for vt, slug in [('number', 'n'), ('string', 's'), ('boolean', 'b')]:
            resp = self._create(slug=slug, name=slug, value_type=vt)
            self.assertEqual(resp.status_code, 201, f'value_type={vt} should be valid')


# --- Cycle 5: retrieve, update, delete --------------------------------------

class CrudTest(SnapshotFieldApiBase):
    def test_get_detail(self):
        pk = self._create().json()['id']
        resp = self._detail(pk)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['slug'], 'price')

    def test_patch_name(self):
        pk = self._create().json()['id']
        resp = self.client.patch(
            reverse('transform_api:snapshotfield-detail', args=[pk]),
            {'name': 'Обновлённая цена'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Обновлённая цена')

    def test_delete(self):
        pk = self._create().json()['id']
        resp = self.client.delete(reverse('transform_api:snapshotfield-detail', args=[pk]))
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self._detail(pk).status_code, 404)
