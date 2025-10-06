from django_filters import filters, FilterSet
from .models import *
from django import forms

class MainProductFilter(FilterSet):
  search = filters.CharFilter(method='search_method', label='Поиск')
  anti_search = filters.CharFilter(method='anti_search_method', label='Исключения')
  category = filters.ModelMultipleChoiceFilter(
        queryset=Category.objects.all(),
        widget=forms.CheckboxSelectMultiple
    )
  supplier = filters.ModelMultipleChoiceFilter(
      field_name='supplier',
      queryset=Supplier.objects.all(),
      widget=forms.SelectMultiple(
          attrs={
              'class': 'form-select select2',
              'data-placeholder': 'Выберите поставщиков'
          }
      )
  )
  manufacturer = filters.ModelMultipleChoiceFilter(
      field_name='manufacturer',
      queryset=Manufacturer.objects.all(),
      widget=forms.SelectMultiple(
          attrs={
              'class': 'form-select select2',
              'data-placeholder': 'Выберите производителей'
          }
      )
  )
  available = filters.BooleanFilter(
      field_name='stock',
      widget=forms.Select(
          attrs={
              'class': 'form-select',
          },
          choices=[('', 'Любой'), ('true', 'В наличии'), ('false', 'Нет в наличии')]
      ),
      label='В наличии',
      method='filter_available'
  )
  class Meta:
    model = MainProduct
    fields = ['search', 'anti_search', 'supplier', 'category', 'manufacturer', 'available']
  def search_method(self, queryset, name, value):
    query = SearchQuery(value, search_type="websearch", config='russian')  # or "websearch" or "plain"
    rank  = SearchRank("search_vector", query)

    queryset = queryset.annotate(rank=rank)

    for bit in value.split(' '):
      query = SearchQuery(bit, search_type="websearch", config='russian')
      queryset = queryset.filter(search_vector=query)      # uses GIN index
    
    return queryset.order_by("-rank")
  def anti_search_method(self, queryset, name, value):
    query = SearchQuery(value, search_type="websearch", config='russian')  # or "websearch" or "plain"
    rank  = SearchRank("search_vector", query)

    anti_queryset = queryset.annotate(rank=rank)

    for bit in value.split(' '):
      query = SearchQuery(bit, search_type="websearch")
      anti_queryset = anti_queryset.filter(search_vector=query)     # uses GIN index
    return queryset.filter(~Q(id__in=anti_queryset))
  def filter_available(self, queryset, name, value):
    if value is True:
      return queryset.filter(stock__gt=0)
    elif value is False:
      return queryset.filter(Q(stock=0)|Q(stock__isnull=True))
    return queryset
  
class SupplierProductFilter(FilterSet):
  class Meta:
    model = SupplierProduct
    fields = ['name']
