from django_filters import filters, FilterSet
from django import forms
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Func
from .models import *

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
  class Meta:
    model = MainProduct
    fields = ['search', 'anti_search', 'supplier', 'category', 'manufacturer', 'available']
  def search_method(self, queryset, name, value):
    if not value:
      return queryset

    bits = [bit.lower() for bit in value.split() if bit.strip()]
    if not bits:
      return queryset

    lexeme_lists = queryset.model.objects.annotate(
      lexemes=Func(
        F('search_vector'),
        function='tsvector_to_array',
        output_field=ArrayField(models.TextField())
      )
    ).values_list('lexemes', flat=True)
    lexemes = set()
    for lexeme_list in lexeme_lists:
      if not lexeme_list:
        continue
      for component in lexeme_list:
        if not component:
          continue
        component_lower = component.lower()
        for bit in bits:
          if bit in component_lower or component_lower in bit:
            lexemes.add(component_lower)
            break
    matched_terms = []
    for bit in bits:
      for component in lexemes:
        ratio = min(len(bit), len(component)) / max(len(bit), len(component))
        if abs(ratio - 1) < .5:
          matched_terms.append(component)
    if not matched_terms:
      return queryset
    matched_terms = list(set(matched_terms))
    search_queries = [Q(search_vector__contains=term) for term in matched_terms]
    combined_query = search_queries[0]
    for query_obj in search_queries[1:]:
      combined_query |= query_obj

    return queryset.filter(combined_query)
  def anti_search_method(self, queryset, name, value):
    query = SearchQuery(value, search_type="websearch")  # or "websearch" or "plain"
    rank  = SearchRank("search_vector", query)

    anti_queryset = queryset.annotate(rank=rank)

    for bit in value.split(' '):
      query = SearchQuery(bit, search_type="websearch")
      anti_queryset = anti_queryset.filter(search_vector=query)     # uses GIN index
    return queryset.filter(~Q(id__in=anti_queryset))
  
class SupplierProductFilter(FilterSet):
  class Meta:
    model = SupplierProduct
    fields = ['name']
