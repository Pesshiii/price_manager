from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier_feed.tests.fixtures import make_feed_mapping
from transform.models import SnapshotField, TransformRule


def make_snapshot_field(slug='price', name='Цена', value_type='number'):
    sf, _ = SnapshotField.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'value_type': value_type},
    )
    return sf


@override_settings(SECURE_SSL_REDIRECT=False)
class TransformRuleApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.feed_mapping = make_feed_mapping()
        cls.target_field = make_snapshot_field()

    def setUp(self):
        self.client.force_login(self.user)

    def _list(self, **params):
        return self.client.get(reverse('transform_api:transformrule-list'), params)

    def _create(self, **kwargs):
        payload = {
            'feed_mapping': self.feed_mapping.id,
            'target_field': self.target_field.id,
            'priority': 10,
            'formula': {'type': 'literal', 'value': 100},
        }
        payload.update(kwargs)
        return self.client.post(
            reverse('transform_api:transformrule-list'),
            payload,
            content_type='application/json',
        )

    def _detail(self, pk):
        return self.client.get(reverse('transform_api:transformrule-detail', args=[pk]))


# --- Cycle 1: tracer bullet -------------------------------------------------

class ListEndpointTest(TransformRuleApiBase):
    def test_list_returns_200_empty(self):
        resp = self._list()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['results'], [])


# --- Cycle 2: create --------------------------------------------------------

class CreateTransformRuleTest(TransformRuleApiBase):
    def test_create_returns_201(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['feed_mapping'], self.feed_mapping.id)
        self.assertEqual(body['target_field'], self.target_field.id)
        self.assertEqual(body['priority'], 10)
        self.assertEqual(body['formula'], {'type': 'literal', 'value': 100})
        self.assertIsNone(body['condition'])

    def test_condition_is_optional(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()['condition'])

    def test_create_with_condition(self):
        cond = {'type': 'AND', 'children': [{'source': 'brand', 'op': 'eq', 'value': 'Acme'}]}
        resp = self._create(condition=cond)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['condition'], cond)

    def test_priority_required(self):
        resp = self._create(priority=None)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('priority', resp.json())


# --- Cycle 3: retrieve ------------------------------------------------------

class RetrieveTransformRuleTest(TransformRuleApiBase):
    def test_get_detail(self):
        pk = self._create().json()['id']
        resp = self._detail(pk)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['id'], pk)
        self.assertEqual(resp.json()['priority'], 10)

    def test_unknown_pk_returns_404(self):
        resp = self._detail(99999)
        self.assertEqual(resp.status_code, 404)


# --- Cycle 4: update --------------------------------------------------------

class UpdateTransformRuleTest(TransformRuleApiBase):
    def test_patch_priority(self):
        pk = self._create().json()['id']
        resp = self.client.patch(
            reverse('transform_api:transformrule-detail', args=[pk]),
            {'priority': 99},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['priority'], 99)

    def test_patch_formula(self):
        pk = self._create().json()['id']
        new_formula = {'type': 'copy', 'source': 'feed', 'key': 'price'}
        resp = self.client.patch(
            reverse('transform_api:transformrule-detail', args=[pk]),
            {'formula': new_formula},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['formula'], new_formula)


# --- Cycle 5: delete --------------------------------------------------------

class DeleteTransformRuleTest(TransformRuleApiBase):
    def test_delete(self):
        pk = self._create().json()['id']
        resp = self.client.delete(reverse('transform_api:transformrule-detail', args=[pk]))
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self._detail(pk).status_code, 404)


# --- Cycle 6: filter by feed_mapping ----------------------------------------

class FeedMappingFilterTest(TransformRuleApiBase):
    def test_filter_returns_rules_for_mapping(self):
        self._create(priority=1)
        self._create(priority=2)
        resp = self._list(feed_mapping=self.feed_mapping.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 2)

    def test_filter_excludes_other_mapping(self):
        self._create(priority=1)
        other_mapping = make_feed_mapping(name='Other')
        resp = self._list(feed_mapping=other_mapping.id)
        self.assertEqual(resp.json()['results'], [])

    def test_no_filter_returns_all(self):
        self._create(priority=1)
        self._create(priority=2)
        resp = self._list()
        self.assertEqual(len(resp.json()['results']), 2)
