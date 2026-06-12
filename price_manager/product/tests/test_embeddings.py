"""Tests for product embedding text builder, hash idempotency, and task."""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from product.models import Brand, Category, CharacteristicType, Product
from product.services import embeddings as emb_svc
from product.tasks import embed_missing_products_task, embed_products_task


class BuildEmbeddingTextTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Кабели')
        self.brand = Brand.objects.create(name='Acme')
        self.color = CharacteristicType.objects.create(
            name='color', label='Цвет', value_type='string'
        )
        self.weight = CharacteristicType.objects.create(
            name='weight', label='Вес', value_type='float', unit='кг'
        )

    def test_includes_name_brand_category_description_and_characteristics(self):
        product = Product.objects.create(
            sku='S1',
            name='HDMI-кабель',
            description='Длина 2м',
            category=self.category,
            brand=self.brand,
            characteristics={'color': 'чёрный', 'weight': 0.25},
        )
        text = emb_svc.build_embedding_text(product)
        self.assertIn('HDMI-кабель', text)
        self.assertIn('Acme', text)
        self.assertIn('Кабели', text)
        self.assertIn('Длина 2м', text)
        self.assertIn('Цвет: чёрный', text)
        self.assertIn('Вес: 0.25 кг', text)

    def test_omits_missing_pieces(self):
        product = Product.objects.create(sku='S2', name='Просто товар')
        text = emb_svc.build_embedding_text(product)
        self.assertEqual(text.strip(), 'Просто товар')


class TextHashTests(TestCase):
    def test_stable_and_distinct(self):
        self.assertEqual(emb_svc.text_hash('abc'), emb_svc.text_hash('abc'))
        self.assertNotEqual(emb_svc.text_hash('abc'), emb_svc.text_hash('abd'))


class EmbedProductsTaskTests(TestCase):
    def setUp(self):
        self.p = Product.objects.create(sku='X1', name='Кабель')

    def test_writes_vector_and_hash(self):
        fake_vec = [0.1] * 256
        with patch('product.tasks.embed_texts', return_value=[fake_vec]) as mock:
            result = embed_products_task([self.p.pk])
        mock.assert_called_once()
        self.p.refresh_from_db()
        self.assertEqual(list(self.p.embedding), fake_vec)
        self.assertTrue(self.p.embedding_text_hash)
        self.assertEqual(result['updated'], 1)

    def test_skips_unchanged_hash(self):
        fake_vec = [0.1] * 256
        with patch('product.tasks.embed_texts', return_value=[fake_vec]):
            embed_products_task([self.p.pk])
        # Second run: nothing changed → embed_texts must NOT be called.
        with patch('product.tasks.embed_texts') as mock:
            result = embed_products_task([self.p.pk])
            mock.assert_not_called()
        self.assertEqual(result['updated'], 0)

    def test_recomputes_when_name_changes(self):
        fake_vec = [0.1] * 256
        with patch('product.tasks.embed_texts', return_value=[fake_vec]):
            embed_products_task([self.p.pk])
        self.p.name = 'Другое имя'
        self.p.save(update_fields=['name'])
        new_vec = [0.9] * 256
        with patch('product.tasks.embed_texts', return_value=[new_vec]) as mock:
            embed_products_task([self.p.pk])
            mock.assert_called_once()
        self.p.refresh_from_db()
        self.assertEqual(list(self.p.embedding), new_vec)


class EmbedMissingProductsTaskTests(TestCase):
    def test_picks_up_only_products_without_embedding(self):
        a = Product.objects.create(sku='A', name='A')
        b = Product.objects.create(sku='B', name='B')
        # Pretend `a` already embedded.
        a.embedding = [0.2] * 256
        a.embedding_text_hash = 'placeholder'
        a.save(update_fields=['embedding', 'embedding_text_hash'])

        with patch('product.tasks.embed_texts', return_value=[[0.3] * 256]) as mock:
            result = embed_missing_products_task()
        # Only b should be embedded.
        called_args = mock.call_args.args[0]
        self.assertEqual(len(called_args), 1)
        b.refresh_from_db()
        self.assertIsNotNone(b.embedding)
        self.assertEqual(result['updated'], 1)
