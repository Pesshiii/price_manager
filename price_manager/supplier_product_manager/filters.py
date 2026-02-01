from django import forms
from django.db.models import Q
from django_filters import FilterSet, filters

from supplier_manager.models import Discount
from .models import SupplierProduct

class SupplierProductFilter(FilterSet):
  search = filters.CharFilter(method='search_method', label='Поиск')
  anti_search = filters.CharFilter(method='anti_search_method', label='Исключения')
  discounts = filters.ModelMultipleChoiceFilter(
    field_name='discounts',
    queryset=Discount.objects.none(),
    widget=forms.SelectMultiple(
      attrs={
        'class': 'form-select select2',
        'data-placeholder': 'Выберите группы скидок'
      }
    ),
    label='Группа скидок'
  )

  class Meta:
    model = SupplierProduct
    fields = ['search', 'anti_search', 'discounts']

  def __init__(self, data=None, queryset=None, *, request=None, prefix=None):
    super().__init__(data=data, queryset=queryset, request=request, prefix=prefix)
    supplier_id = None
    if request is not None and request.resolver_match:
      supplier_id = request.resolver_match.kwargs.get('id')
    if supplier_id:
      self.filters['discounts'].queryset = Discount.objects.filter(supplier_id=supplier_id)
    else:
      self.filters['discounts'].queryset = Discount.objects.none()

  def _build_search_terms(self, value):
    terms = [bit for bit in value.split() if bit]
    return terms

  def _build_search_query(self, terms):
    if not terms:
      return None
    query = Q()
    for term in terms:
      query &= (
        Q(name__icontains=term) |
        Q(article__icontains=term) |
        Q(category__name__icontains=term) |
        Q(manufacturer__name__icontains=term)
      )
    return query

  def search_method(self, queryset, name, value):
    terms = self._build_search_terms(value)
    query = self._build_search_query(terms)
    if query is None:
      return queryset
    return queryset.filter(query)

  def anti_search_method(self, queryset, name, value):
    terms = self._build_search_terms(value)
    query = self._build_search_query(terms)
    if query is None:
      return queryset
    return queryset.exclude(query)
