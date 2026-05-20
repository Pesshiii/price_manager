"""Product embedding helpers.

Wraps the Ollama-compatible ``/api/embed`` endpoint exposed by the
``embedder`` docker service (EmbeddingGemma, 768-dim native, truncated to 256
via Matryoshka). Two semantic call sites:

* :func:`embed_texts` — used when indexing products (task_type=document).
* :func:`embed_query` — used when searching (task_type=query). EmbeddingGemma
  was trained with asymmetric query/doc prompts; keeping them separate gives
  noticeably better retrieval quality than a single embed mode.

The HTTP layer raises :class:`EmbeddingServiceError` on any non-2xx / network
failure; callers decide whether that translates to a 5xx (search) or a retry
(background tasks).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterable

import httpx
from django.conf import settings

from ..models import PRODUCT_EMBEDDING_DIM, CharacteristicType, Product

logger = logging.getLogger(__name__)


class EmbeddingServiceError(RuntimeError):
    """Raised when the embedder is unreachable or returns an unexpected payload."""


def _flatten_characteristics(chars: dict, types_by_name: dict[str, CharacteristicType]) -> str:
    if not isinstance(chars, dict) or not chars:
        return ''
    parts: list[str] = []
    for key, value in chars.items():
        if value is None or value == '':
            continue
        if isinstance(value, (list, dict)):
            continue
        ct = types_by_name.get(key)
        label = ct.label if ct and ct.label else key
        unit = f' {ct.unit}' if ct and ct.unit else ''
        parts.append(f'{label}: {value}{unit}')
    return '; '.join(parts)


def build_embedding_text(
    product: Product,
    types_by_name: dict[str, CharacteristicType] | None = None,
) -> str:
    """Concatenate the indexable fields of a product into one string.

    Caller may pass ``types_by_name`` to avoid N+1 lookups when embedding many
    products in a batch; otherwise we query for just this product's keys.
    """
    if types_by_name is None:
        keys = list((product.characteristics or {}).keys())
        types_by_name = {
            ct.name: ct
            for ct in CharacteristicType.objects.filter(name__in=keys).only(
                'name', 'label', 'unit'
            )
        } if keys else {}

    bits: list[str] = [product.name or '']
    if product.brand_id and product.brand:
        bits.append(product.brand.name)
    if product.category_id and product.category:
        bits.append(product.category.name)
    if product.description:
        bits.append(product.description)
    chars_text = _flatten_characteristics(product.characteristics or {}, types_by_name)
    if chars_text:
        bits.append(chars_text)
    return '\n'.join(b for b in bits if b)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# EmbeddingGemma was trained with task-specific prompt prefixes (see Google's
# model card). Ollama does NOT honour ``options.task_type`` — it has to be
# baked into the input text on the client side.
DOC_PREFIX = 'title: none | text: '
QUERY_PREFIX = 'task: search result | query: '


def _truncate(vector: list[float]) -> list[float]:
    """Matryoshka client-side truncation to ``PRODUCT_EMBEDDING_DIM``."""
    return vector[:PRODUCT_EMBEDDING_DIM]


def _post_embed(inputs: list[str]) -> list[list[float]]:
    payload = {
        'model': settings.OLLAMA_EMBED_MODEL,
        'input': inputs,
    }
    url = f"{settings.OLLAMA_EMBED_URL.rstrip('/')}/api/embed"
    try:
        with httpx.Client(timeout=settings.OLLAMA_EMBED_TIMEOUT) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise EmbeddingServiceError(f'embedder request failed: {exc}') from exc

    vectors = data.get('embeddings')
    if not vectors or len(vectors) != len(inputs):
        raise EmbeddingServiceError(
            f'embedder returned {len(vectors) if vectors else 0} vectors for {len(inputs)} inputs'
        )
    return [_truncate(v) for v in vectors]


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Generate document-side embeddings for a batch of texts."""
    inputs = [f'{DOC_PREFIX}{t or " "}' for t in texts]
    if not inputs:
        return []
    return _post_embed(inputs)


def embed_query(text: str) -> list[float]:
    """Generate a query-side embedding (asymmetric to document side)."""
    vectors = _post_embed([f'{QUERY_PREFIX}{text or " "}'])
    return vectors[0]
