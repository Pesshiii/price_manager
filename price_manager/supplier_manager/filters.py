from django_filters import FilterSet
from django.contrib.postgres.search import SearchQuery
from django.db.models import Count, F, Q, Case, When, Value, IntegerField

from .models import Category


class CategoryFilter(FilterSet):
    class Meta:
        model = Category
        fields = []

    def __init__(self, data=None, product_qs=None, search_query=None, **kwargs):
        if product_qs is not None:
            kwargs.setdefault('queryset', Category.objects.filter(
                pk__in=product_qs.values_list('categories__pk')
            ).select_related(
                'parent__parent__parent__parent'
            ).annotate(
                mps_count=Count(F('mainproducts'), distinct=True)
            ).filter(~Q(mps_count=0)))
        self._search_query = SearchQuery(search_query, config='russian') if search_query else None
        super().__init__(data, **kwargs)

    @property
    def qs(self):
        if not hasattr(self, '_cat_qs'):
            qs = super().qs
            if self._search_query:
                qs = qs.annotate(
                    cat_match=Case(
                        When(search_vector=self._search_query, then=Value(0)),
                        default=Value(1),
                        output_field=IntegerField()
                    )
                ).order_by('cat_match')
            self._cat_qs = qs
        return self._cat_qs
