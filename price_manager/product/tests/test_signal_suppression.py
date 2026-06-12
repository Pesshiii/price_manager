"""Behavior of suppress_embedding_signal() — opt-out used by the importer."""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, TransactionTestCase

from product.models import Product
from product.signals import suppress_embedding_signal


class SuppressEmbeddingSignalTests(TransactionTestCase):
    """Uses TransactionTestCase so transaction.on_commit actually fires."""

    def test_signal_fires_outside_suppression(self):
        with patch('product.tasks.embed_products_task.delay') as delay_mock:
            Product.objects.create(sku='S-OUT', name='N')
        self.assertEqual(delay_mock.call_count, 1)
        # Signal hands the task a single-pk list.
        args = delay_mock.call_args_list[0].args[0]
        self.assertEqual(len(args), 1)

    def test_signal_suppressed_within_context(self):
        with patch('product.tasks.embed_products_task.delay') as delay_mock:
            with suppress_embedding_signal():
                Product.objects.create(sku='S-IN', name='N')
        self.assertEqual(delay_mock.call_count, 0)

    def test_suppression_restores_after_context_exits(self):
        with patch('product.tasks.embed_products_task.delay') as delay_mock:
            with suppress_embedding_signal():
                Product.objects.create(sku='S-1', name='N')
            # Out of the context now — signal should fire again.
            Product.objects.create(sku='S-2', name='N')
        self.assertEqual(delay_mock.call_count, 1)

    def test_nested_suppression_keeps_outer_intact(self):
        """An inner with-block exiting must not re-enable the signal too early."""
        with patch('product.tasks.embed_products_task.delay') as delay_mock:
            with suppress_embedding_signal():
                with suppress_embedding_signal():
                    Product.objects.create(sku='N-1', name='N')
                # Still inside outer suppression — no task expected.
                Product.objects.create(sku='N-2', name='N')
        self.assertEqual(delay_mock.call_count, 0)


class ImporterSerializerProgressTests(TestCase):
    """ImportJobSerializer exposes the new progress fields."""

    def test_serializer_includes_progress_fields(self):
        from product.api.serializers import ImportJobSerializer
        from product.models import ImportJob

        job = ImportJob.objects.create(
            kind=ImportJob.KIND_COMMIT,
            session_id='dummy',
            instructions={},
            mapping={},
            rows_total=12,
            rows_done=5,
            stage='Записываем в БД',
        )
        data = ImportJobSerializer(job).data
        self.assertIn('stage', data)
        self.assertIn('rows_total', data)
        self.assertIn('rows_done', data)
        self.assertEqual(data['rows_total'], 12)
        self.assertEqual(data['rows_done'], 5)
        self.assertEqual(data['stage'], 'Записываем в БД')
