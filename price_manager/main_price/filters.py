from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Q
from django_filters import FilterSet, filters

from main_price.models import Category, MainProduct, Manufacturer
from supplier_manager.models import Supplier


class MainProductFilter(FilterSet):
    search = filters.CharFilter(method='search_method', label='Поиск')
    anti_search = filters.CharFilter(method='anti_search_method', label='Исключения')
    category = filters.ModelMultipleChoiceFilter(
        queryset=Category.objects.all(),
        widget=forms.CheckboxSelectMultiple,
    )
    supplier = filters.ModelMultipleChoiceFilter(
        field_name='supplier',
        queryset=Supplier.objects.all(),
        widget=forms.SelectMultiple(
            attrs={'class': 'form-select select2', 'data-placeholder': 'Выберите поставщиков'}
        ),
    )
    manufacturer = filters.ModelMultipleChoiceFilter(
        field_name='manufacturer',
        queryset=Manufacturer.objects.all(),
        widget=forms.SelectMultiple(
            attrs={'class': 'form-select select2', 'data-placeholder': 'Выберите производителей'}
        ),
    )
    available = filters.BooleanFilter(
        field_name='stock',
        widget=forms.Select(
            attrs={'class': 'form-select'},
            choices=[('', 'Любой'), ('true', 'В наличии'), ('false', 'Нет в наличии')],
        ),
        label='В наличии',
        method='filter_available',
    )

    class Meta:
        model = MainProduct
        fields = ['search', 'anti_search', 'supplier', 'category', 'manufacturer', 'available']

    def _build_partial_query(self, value):
        terms = [bit for bit in value.split() if bit]
        if not terms:
            return None
        raw_query = ' & '.join(f"{term}:*" for term in terms)
        return SearchQuery(raw_query, search_type='raw', config='russian')

    def search_method(self, queryset, name, value):
        query = self._build_partial_query(value)
        if query is None:
            return queryset
        rank = SearchRank('search_vector', query)
        return queryset.annotate(rank=rank).filter(search_vector=query).order_by('-rank')

    def anti_search_method(self, queryset, name, value):
        query = self._build_partial_query(value)
        if query is None:
            return queryset
        rank = SearchRank('search_vector', query)
        anti_queryset = queryset.annotate(rank=rank).filter(search_vector=query)
        return queryset.filter(~Q(id__in=anti_queryset))

    def filter_available(self, queryset, name, value):
        if value is True:
            return queryset.filter(stock__gt=0)
        if value is False:
            return queryset.filter(Q(stock=0) | Q(stock__isnull=True))
        return queryset
