from __future__ import annotations

import django_filters
from django.db.models import Q

from .models import Brand, Category, Product


class ProductFilter(django_filters.FilterSet):
    """Filter Products by category (incl. MPTT descendants), brand, status, free-text q,
    and arbitrary characteristics via ?char__<type_name>=<value>.
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

    def filter_q(self, qs, name, value):
        if not value:
            return qs
        return qs.filter(Q(name__icontains=value) | Q(sku__icontains=value))

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
