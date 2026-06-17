from __future__ import annotations

import django_filters
from decimal import Decimal, InvalidOperation

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db import connection
from django.db.models import Exists, OuterRef, Q

from .models import Brand, Category, Product


def _query_lexemes(value: str) -> list[str]:
    """Return Russian Snowball lexemes for value via PostgreSQL to_tsvector('russian', ...)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT array_agg(lexeme) FROM unnest(to_tsvector('russian', %s))",
            [value],
        )
        row = cursor.fetchone()
    return row[0] if row and row[0] else []


class ProductFilter(django_filters.FilterSet):
    """Filter Products by category (incl. MPTT descendants), brand, status, and free-text q."""

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

    def filter_q(self, qs, name, value):
        if not value:
            return qs

        lexemes = _query_lexemes(value)

        if not lexemes:
            # Short/numeric query — no lexemes produced; fall back to word-similar on raw value.
            return qs.filter(Q(name__trigram_word_similar=value) | Q(sku__icontains=value))

        # Pre-filter via GIN index: any stemmed token word-similar to name, OR sku matches.
        # word_similar (<%) checks against any word in name, not the whole string —
        # critical for multi-word product names like "Лопата штыковая нержавеющая".
        q = Q(sku__icontains=value)
        for lexeme in lexemes:
            q |= Q(name__trigram_word_similar=lexeme)

        # Re-rank by word similarity of the original (unstemmed) query so best matches rise first.
        return (
            qs.filter(q)
              .annotate(_sim=TrigramWordSimilarity(value, 'name'))
              .order_by('-_sim', '-updated_at')
        )

    def filter_category(self, qs, name, value):
        if value is None:
            return qs
        descendants = value.get_descendants(include_self=True)
        return qs.filter(category__in=descendants)

    @property
    def qs(self):
        parent_qs = super().qs
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

        # Apply ?price_type=<slug>&price_min=<n>&price_max=<n> filter.
        price_type_slug = self.request.GET.get('price_type') if self.request else None
        if price_type_slug:
            from pricing.models import ProductPrice
            price_qs = ProductPrice.objects.filter(
                product=OuterRef('pk'),
                price_type__name=price_type_slug,
            )
            price_min = self.request.GET.get('price_min')
            price_max = self.request.GET.get('price_max')
            if price_min:
                try:
                    price_qs = price_qs.filter(value__gte=Decimal(price_min))
                except InvalidOperation:
                    return parent_qs.none()
            if price_max:
                try:
                    price_qs = price_qs.filter(value__lte=Decimal(price_max))
                except InvalidOperation:
                    return parent_qs.none()
            parent_qs = parent_qs.filter(Exists(price_qs))

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
