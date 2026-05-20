"""Tests for the async CharacteristicType retype/rename flow.

Two layers:

* ``preview_retype`` / ``preview_rename`` services — pure functions, tested
  directly.
* ``run_char_retype`` / ``run_char_rename`` Celery tasks — exercised through
  the HTTP endpoints with ``CELERY_TASK_ALWAYS_EAGER`` (same pattern as
  ``test_import_async.py``) so the request returns after the worker completes.
"""
from __future__ import annotations

import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from product.models import (
    CharacteristicMutationJob,
    CharacteristicType,
    Product,
)
from product.services.char_mutation import preview_rename, preview_retype

from .fixtures import make_char_type


def _make_product(sku, chars):
    # Bypass Product.clean() — we deliberately want to seed pre-existing
    # garbage values that the new value_type would normally reject.
    return Product.objects.create(sku=sku, name=sku, characteristics=chars)


class PreviewRetypeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ct = make_char_type('weight', CharacteristicType.VALUE_STRING)
        _make_product('S1', {'weight': '10'})
        _make_product('S2', {'weight': '20'})
        _make_product('S3', {'weight': 'около десяти'})
        _make_product('S4', {'weight': 'около десяти'})  # dup raw → bucket count 2
        _make_product('S5', {'weight': ''})  # empty → not counted as invalid
        _make_product('S6', {'other_char': 'x'})  # no key → ignored

    def test_total_with_key_excludes_products_without_key(self):
        result = preview_retype(self.ct, CharacteristicType.VALUE_INTEGER)
        self.assertEqual(result['total_with_key'], 5)

    def test_invalid_count_and_unique_grouping(self):
        result = preview_retype(self.ct, CharacteristicType.VALUE_INTEGER)
        self.assertEqual(result['invalid_count'], 2)
        self.assertEqual(result['unique_invalid'], [
            {'value': 'около десяти', 'count': 2},
        ])
        self.assertFalse(result['truncated'])

    def test_clean_retype_reports_zero_invalid(self):
        # integer → float never fails
        ct = make_char_type('count', CharacteristicType.VALUE_INTEGER)
        _make_product('I1', {'count': 1})
        _make_product('I2', {'count': 2})
        result = preview_retype(ct, CharacteristicType.VALUE_FLOAT)
        self.assertEqual(result['invalid_count'], 0)
        self.assertEqual(result['unique_invalid'], [])

    def test_unknown_target_type_raises(self):
        with self.assertRaises(ValueError):
            preview_retype(self.ct, 'nonsense')


class PreviewRenameTests(TestCase):
    def test_collision_detection(self):
        ct = make_char_type('weight', CharacteristicType.VALUE_STRING)
        _make_product('S1', {'weight': '10'})
        _make_product('S2', {'weight': '20', 'mass': 'already-here'})  # collision
        _make_product('S3', {'weight': '30'})

        result = preview_rename(ct, 'mass')
        self.assertEqual(result['total_to_rename'], 3)
        self.assertEqual(result['collision_count'], 1)
        self.assertEqual(len(result['collisions']), 1)
        self.assertEqual(result['collisions'][0]['sku'], 'S2')

    def test_rejects_same_name(self):
        ct = make_char_type('weight', CharacteristicType.VALUE_STRING)
        with self.assertRaises(ValueError):
            preview_rename(ct, 'weight')


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='prod_char_mut_'),
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
)
class RetypeCommitTaskTests(TestCase):
    """End-to-end retype: POST to /retype/commit/, eager Celery runs the task
    synchronously, then assert products + CharacteristicType state."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')
        cls.ct = make_char_type('weight', CharacteristicType.VALUE_STRING)
        _make_product('S1', {'weight': '10'})
        _make_product('S2', {'weight': '20'})
        _make_product('S3', {'weight': 'около десяти'})
        _make_product('S4', {'weight': 'много'})

    def setUp(self):
        self.client.force_login(self.user)

    def _commit(self, body):
        return self.client.post(
            reverse('product_api:characteristic-type-retype-commit', args=[self.ct.id]),
            body,
            content_type='application/json',
        )

    def test_fallback_drop_removes_invalid_keys(self):
        resp = self._commit({'new_value_type': 'integer', 'fallback': 'drop'})
        self.assertEqual(resp.status_code, 202, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['result']['updated'], 4)
        self.assertEqual(body['result']['dropped'], 2)

        # Type was actually flipped.
        self.ct.refresh_from_db()
        self.assertEqual(self.ct.value_type, 'integer')

        # Valid rows are now typed ints; invalid rows lost the key.
        s1 = Product.objects.get(sku='S1')
        self.assertEqual(s1.characteristics, {'weight': 10})
        s3 = Product.objects.get(sku='S3')
        self.assertEqual(s3.characteristics, {})

    def test_fallback_default_substitutes_value(self):
        resp = self._commit({
            'new_value_type': 'integer',
            'fallback': 'default',
            'default_value': '0',
        })
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['result']['defaulted'], 2)
        s3 = Product.objects.get(sku='S3')
        self.assertEqual(s3.characteristics, {'weight': 0})

    def test_value_map_overrides_fallback(self):
        resp = self._commit({
            'new_value_type': 'integer',
            'fallback': 'drop',
            'value_map': {'около десяти': '10', 'много': '100'},
        })
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body['result']['mapped'], 2)
        self.assertEqual(body['result']['dropped'], 0)

        s3 = Product.objects.get(sku='S3')
        s4 = Product.objects.get(sku='S4')
        self.assertEqual(s3.characteristics, {'weight': 10})
        self.assertEqual(s4.characteristics, {'weight': 100})

    def test_value_map_partial_falls_back_for_unmapped(self):
        resp = self._commit({
            'new_value_type': 'integer',
            'fallback': 'drop',
            'value_map': {'около десяти': '10'},  # 'много' not mapped → drop
        })
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body['result']['mapped'], 1)
        self.assertEqual(body['result']['dropped'], 1)

    def test_invalid_fallback_returns_400_and_no_job(self):
        before = CharacteristicMutationJob.objects.count()
        resp = self._commit({'new_value_type': 'integer', 'fallback': 'magic'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(CharacteristicMutationJob.objects.count(), before)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='prod_char_mut_rn_'),
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
)
class RenameCommitTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

    def setUp(self):
        self.client.force_login(self.user)

    def _commit(self, ct_id, body):
        return self.client.post(
            reverse('product_api:characteristic-type-rename-commit', args=[ct_id]),
            body,
            content_type='application/json',
        )

    def test_simple_rename_without_collision(self):
        ct = make_char_type('weight', CharacteristicType.VALUE_STRING)
        _make_product('S1', {'weight': '10'})
        _make_product('S2', {'weight': '20'})

        resp = self._commit(ct.id, {'new_name': 'mass'})
        self.assertEqual(resp.status_code, 202, resp.content[:300])
        body = resp.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['result']['renamed'], 2)
        self.assertEqual(body['result']['collisions'], 0)

        ct.refresh_from_db()
        self.assertEqual(ct.name, 'mass')

        s1 = Product.objects.get(sku='S1')
        self.assertEqual(s1.characteristics, {'mass': '10'})

    def test_collision_overwrite(self):
        ct = make_char_type('weight', CharacteristicType.VALUE_STRING)
        _make_product('S1', {'weight': '10', 'mass': 'pre-existing'})

        resp = self._commit(ct.id, {'new_name': 'mass', 'on_conflict': 'overwrite'})
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()['result']['renamed'], 1)
        self.assertEqual(resp.json()['result']['collisions'], 1)

        s1 = Product.objects.get(sku='S1')
        self.assertEqual(s1.characteristics, {'mass': '10'})

    def test_collision_keep_existing(self):
        ct = make_char_type('weight', CharacteristicType.VALUE_STRING)
        _make_product('S1', {'weight': '10', 'mass': 'pre-existing'})

        resp = self._commit(ct.id, {'new_name': 'mass', 'on_conflict': 'keep_existing'})
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body['result']['renamed'], 1)

        s1 = Product.objects.get(sku='S1')
        self.assertEqual(s1.characteristics, {'mass': 'pre-existing'})

    def test_collision_skip_row(self):
        ct = make_char_type('weight', CharacteristicType.VALUE_STRING)
        _make_product('S1', {'weight': '10', 'mass': 'pre-existing'})
        _make_product('S2', {'weight': '20'})

        resp = self._commit(ct.id, {'new_name': 'mass', 'on_conflict': 'skip_row'})
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body['result']['renamed'], 1)
        self.assertEqual(body['result']['skipped'], 1)

        s1 = Product.objects.get(sku='S1')  # untouched
        self.assertEqual(s1.characteristics, {'weight': '10', 'mass': 'pre-existing'})
        s2 = Product.objects.get(sku='S2')  # renamed
        self.assertEqual(s2.characteristics, {'mass': '20'})

    def test_rename_to_existing_type_name_blocked_before_job(self):
        make_char_type('weight', CharacteristicType.VALUE_STRING)
        other = make_char_type('mass', CharacteristicType.VALUE_STRING)
        # Now rename 'weight' → 'mass' (a type that already exists). Must 400.
        ct = CharacteristicType.objects.get(name='weight')
        before = CharacteristicMutationJob.objects.count()
        resp = self._commit(ct.id, {'new_name': 'mass'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(CharacteristicMutationJob.objects.count(), before)
        # Confirm `other` still exists, untouched
        other.refresh_from_db()
        self.assertEqual(other.name, 'mass')


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
)
class CharMutationJobPollingTests(TestCase):
    """The polling endpoint mirrors ImportJobView — user scoping, 404 for others."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u1', password='p')
        cls.other = User.objects.create_user(username='u2', password='p')
        cls.ct = make_char_type('color', CharacteristicType.VALUE_STRING)

    def setUp(self):
        self.client.force_login(self.user)

    def _start_retype(self):
        return self.client.post(
            reverse('product_api:characteristic-type-retype-commit', args=[self.ct.id]),
            {'new_value_type': 'string', 'fallback': 'drop'},  # noop retype is fine
            content_type='application/json',
        )

    def test_poll_returns_job_envelope_with_stage(self):
        resp = self._start_retype()
        self.assertEqual(resp.status_code, 202)
        job_id = resp.json()['id']

        poll = self.client.get(
            reverse('product_api:char-mutation-job', args=[job_id])
        )
        self.assertEqual(poll.status_code, 200)
        body = poll.json()
        self.assertEqual(body['status'], 'success')
        # Stage is cleared on terminal status.
        self.assertEqual(body['stage'], '')
        self.assertIn('result', body)

    def test_other_user_gets_404(self):
        job_id = self._start_retype().json()['id']
        self.client.force_login(self.other)
        resp = self.client.get(
            reverse('product_api:char-mutation-job', args=[job_id])
        )
        self.assertEqual(resp.status_code, 404)
