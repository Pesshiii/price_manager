"""Tests for hybrid (lexical + vector) search via ProductFilter."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from product.filters import _rrf_merge
from product.models import Product
from product.services.embeddings import EmbeddingServiceError


class RRFMergeTests(TestCase):
    def test_higher_rank_in_both_lists_wins(self):
        lex = [1, 2, 3]
        vec = [2, 3, 1]
        merged = _rrf_merge(lex, vec)
        # 2: 1/62 + 1/61 (top of vec, mid of lex) — highest sum.
        # 1: 1/61 + 1/63 — second.
        # 3: 1/63 + 1/62 — last.
        self.assertEqual(merged, [2, 1, 3])

    def test_empty_lists(self):
        self.assertEqual(_rrf_merge([], []), [])
        self.assertEqual(_rrf_merge([5], []), [5])


class HybridSearchAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('u', password='p')
        self.client = Client()
        self.client.force_login(self.user)

        # Lexical-match candidate
        self.lex = Product.objects.create(sku='LEX', name='HDMI кабель 2м')
        # Vector-bearing candidate so the hybrid path actually exercises vectors
        self.vec = Product.objects.create(sku='VEC', name='Шнур цифровой')
        self.vec.embedding = [0.1] * 256
        self.vec.embedding_text_hash = 'h'
        self.vec.save(update_fields=['embedding', 'embedding_text_hash'])
        Product.objects.create(sku='OTH', name='Розетка')

    def test_lexical_only_when_no_vectors_in_db(self):
        # Wipe vectors → hybrid path must skip the embedder altogether.
        Product.objects.update(embedding=None, embedding_text_hash='')
        with patch('product.filters.embed_query') as mock_embed:
            resp = self.client.get('/api/products/products/?q=кабель')
        mock_embed.assert_not_called()
        self.assertEqual(resp.status_code, 200)
        skus = [r['sku'] for r in resp.json()['results']]
        self.assertIn('LEX', skus)

    def test_503_when_embedder_down(self):
        with patch(
            'product.filters.embed_query',
            side_effect=EmbeddingServiceError('boom'),
        ):
            resp = self.client.get('/api/products/products/?q=кабель')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('Embedding service unavailable', resp.json()['detail'])

    def test_lexical_mode_skips_embedder(self):
        with patch('product.filters.embed_query') as mock_embed:
            resp = self.client.get('/api/products/products/?q=кабель&search_mode=lexical')
        mock_embed.assert_not_called()
        self.assertEqual(resp.status_code, 200)
