from __future__ import annotations

import django_filters
from django.db.models import Case, Q, When
from pgvector.django import CosineDistance

from .models import Brand, Category, Product
from .services.embeddings import embed_query

HYBRID_LEXICAL_LIMIT = 100
HYBRID_VECTOR_LIMIT = 100
RRF_K = 60


def _rrf_merge(lexical_ids: list[int], vector_ids: list[int]) -> list[int]:
    """Reciprocal Rank Fusion. Higher = better. Returns ids ordered by fused score."""
    scores: dict[int, float] = {}
    for rank, pk in enumerate(lexical_ids):
        scores[pk] = scores.get(pk, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, pk in enumerate(vector_ids):
        scores[pk] = scores.get(pk, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


class ProductFilter(django_filters.FilterSet):
    """Filter Products by category (incl. MPTT descendants), brand, status, free-text q,
    and arbitrary characteristics via ?char__<type_name>=<value>.

    Free-text ``q`` is hybrid: lexical icontains over name/sku merged with
    cosine-similarity over the ``embedding`` column via Reciprocal Rank Fusion.
    Override via ``?search_mode=lexical|vector|hybrid`` (default: hybrid).
    """

    q = django_filters.CharFilter(method='filter_q')
    category = django_filters.ModelChoiceFilter(
        queryset=Category.objects.all(),
        method='filter_category',
    )
    brand = django_filters.ModelChoiceFilter(queryset=Brand.objects.all())
    status = django_filters.CharFilter(field_name='status')

    class Meta:
        model = Product
        fields = ['q', 'category', 'brand', 'status']

    def _resolved_mode(self) -> str:
        if self.request is None:
            return 'hybrid'
        raw = (self.request.GET.get('search_mode') or 'hybrid').lower()
        return raw if raw in {'lexical', 'vector', 'hybrid'} else 'hybrid'

    def _lexical_qs(self, qs, value):
        return qs.filter(Q(name__icontains=value) | Q(sku__icontains=value))

    def _vector_ids(self, qs, value):
        # `embed_query` raises EmbeddingServiceError on embedder failure; let it
        # bubble up — DRF will translate to a 500 with a useful message.
        vector = embed_query(value)
        return list(
            qs.filter(embedding__isnull=False)
            .annotate(_dist=CosineDistance('embedding', vector))
            .order_by('_dist')
            .values_list('pk', flat=True)[:HYBRID_VECTOR_LIMIT]
        )

    def filter_q(self, qs, name, value):
        if not value:
            return qs
        mode = self._resolved_mode()

        if mode == 'lexical':
            return self._lexical_qs(qs, value)

        # Skip the embedder entirely when the catalog has no vectors yet —
        # otherwise a fresh DB (or a test suite that never seeds vectors) would
        # always return 503 just because there's nothing to match against.
        # `vector` mode bypasses the precheck so an explicit caller still sees
        # the error rather than silently degrading.
        if mode == 'hybrid' and not Product.objects.filter(embedding__isnull=False).exists():
            return self._lexical_qs(qs, value)

        if mode == 'vector':
            vector_ids = self._vector_ids(qs, value)
            if not vector_ids:
                # No vectors indexed yet → fall through to lexical to avoid
                # returning an empty page on a freshly migrated catalog.
                return self._lexical_qs(qs, value)
            return qs.filter(pk__in=vector_ids).order_by(
                Case(*[When(pk=pk, then=idx) for idx, pk in enumerate(vector_ids)])
            )

        # hybrid (default)
        lexical_ids = list(
            self._lexical_qs(qs, value).values_list('pk', flat=True)[:HYBRID_LEXICAL_LIMIT]
        )
        vector_ids = self._vector_ids(qs, value)
        if not lexical_ids and not vector_ids:
            return qs.none()
        if not vector_ids:
            # Embedder is up but nothing has been indexed yet — pure lexical.
            ranked = lexical_ids
        elif not lexical_ids:
            ranked = vector_ids
        else:
            ranked = _rrf_merge(lexical_ids, vector_ids)
        return qs.filter(pk__in=ranked).order_by(
            Case(*[When(pk=pk, then=idx) for idx, pk in enumerate(ranked)])
        )

    def filter_category(self, qs, name, value):
        if value is None:
            return qs
        descendants = value.get_descendants(include_self=True)
        return qs.filter(category__in=descendants)

    @property
    def qs(self):
        parent_qs = super().qs
        if self.request:
            raw = self.request.GET.get('category__isnull')
            if raw is not None:
                is_null = raw.lower() in ('1', 'true', 'yes', 'y', 'on')
                parent_qs = parent_qs.filter(category__isnull=is_null)
        # Apply ?char__<name>=<value> dynamic filters.
        for key, val in self.request.GET.lists() if self.request else []:
            if not key.startswith('char__'):
                continue
            char_name = key[len('char__'):]
            if not char_name:
                continue
            if len(val) == 1:
                parent_qs = parent_qs.filter(
                    characteristics__contains={char_name: _coerce_filter_value(val[0])}
                )
            else:
                # Multi-value: union via OR over JSONB contains.
                or_q = Q()
                for v in val:
                    or_q |= Q(characteristics__contains={char_name: _coerce_filter_value(v)})
                parent_qs = parent_qs.filter(or_q)
        return parent_qs


def _coerce_filter_value(value: str):
    """Best-effort coercion of a query-string value so JSONB __contains matches numeric/bool values.

    JSONB equality is type-sensitive: 5 != "5". We try int → float → bool → string.
    """
    if value is None:
        return None
    s = str(value)
    try:
        return int(s)
    except (TypeError, ValueError):
        pass
    try:
        f = float(s)
        if f == f:  # not NaN
            return f
    except (TypeError, ValueError):
        pass
    low = s.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    return s
