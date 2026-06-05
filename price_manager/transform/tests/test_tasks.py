"""Integration tests for transform.tasks.run_transform_task."""
from unittest.mock import patch

from django.test import TestCase, override_settings

from supplier_feed.models import SupplierFeed, SupplierFeedEntry
from supplier_feed.tests.fixtures import make_feed_mapping, make_product
from transform.models import ProductSnapshot, SnapshotField, TransformRule


def _make_field(slug='price', name='Цена', value_type='number'):
    sf, _ = SnapshotField.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'value_type': value_type},
    )
    return sf


def _setup(status='done'):
    fm = make_feed_mapping()
    product = make_product()
    field = _make_field('price')
    TransformRule.objects.create(
        feed_mapping=fm, target_field=field, priority=10,
        condition=None, formula={'type': 'literal', 'value': 99},
    )
    feed = SupplierFeed.objects.create(supplier=fm.supplier, feed_mapping=fm, status=status)
    entry = SupplierFeedEntry.objects.create(
        feed=feed, supplier_sku='A001', data={'raw_price': 99}, product=product,
    )
    return feed, entry, product


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class RunTransformTaskTest(TestCase):
    # --- Cycle 1: tracer bullet — snapshot created with correct data ---

    def test_snapshot_created_for_matched_entry(self):
        from transform.tasks import run_transform_task
        feed, entry, product = _setup()

        run_transform_task.apply(args=[feed.pk])

        snap = ProductSnapshot.objects.get(product=product, supplier=feed.feed_mapping.supplier)
        self.assertEqual(snap.data, {'price': 99})
        self.assertEqual(snap.source_feed, feed)

    # --- Cycle 2: idempotency — calling again updates, count stays 1 ---

    def test_idempotent_second_call_updates_not_duplicates(self):
        from transform.tasks import run_transform_task
        feed, entry, product = _setup()

        run_transform_task.apply(args=[feed.pk])
        # Update entry data so we can detect re-run
        entry.data = {'raw_price': 200}
        entry.save()
        # Update formula to return new value
        TransformRule.objects.filter(feed_mapping=feed.feed_mapping).update(
            formula={'type': 'literal', 'value': 200},
        )

        run_transform_task.apply(args=[feed.pk])

        self.assertEqual(ProductSnapshot.objects.filter(product=product).count(), 1)
        snap = ProductSnapshot.objects.get(product=product)
        self.assertEqual(snap.data, {'price': 200})

    # --- Cycle 3: entries with product=None are skipped ---

    def test_unmatched_entry_skipped(self):
        from transform.tasks import run_transform_task
        fm = make_feed_mapping()
        field = _make_field('price')
        TransformRule.objects.create(
            feed_mapping=fm, target_field=field, priority=10,
            condition=None, formula={'type': 'literal', 'value': 99},
        )
        feed = SupplierFeed.objects.create(supplier=fm.supplier, feed_mapping=fm, status='done')
        SupplierFeedEntry.objects.create(
            feed=feed, supplier_sku='X001', data={}, product=None,
        )

        run_transform_task.apply(args=[feed.pk])

        self.assertEqual(ProductSnapshot.objects.count(), 0)

    # --- Cycle 4: missing feed id → returns silently ---

    def test_missing_feed_id_returns_silently(self):
        from transform.tasks import run_transform_task
        run_transform_task.apply(args=[99999])  # no exception

    # --- Cycle 5: lock held → no snapshot created ---

    def test_lock_prevents_second_run(self):
        from transform.tasks import run_transform_task
        feed, entry, product = _setup()

        with patch('transform.tasks.cache.add', return_value=False):
            run_transform_task.apply(args=[feed.pk])

        self.assertEqual(ProductSnapshot.objects.count(), 0)
