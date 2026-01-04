from django_filters import filters, FilterSet
from .models import Category, Supplier, Manufacturer, MainProduct
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Q


from django.urls import reverse_lazy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field

from mptt.forms import TreeNodeMultipleChoiceField


import re


class MainProductFilter(FilterSet):
  class Meta:
    model = MainProduct
    fields = ['search', 'category']


  search = filters.CharFilter(
    method='search_method',
    label='Поиск',
    widget=forms.TextInput(
      attrs={'class': 'mt-2'}
    )
  )
  
  category = filters.ModelMultipleChoiceFilter(
    queryset=Category.objects.all(),
    widget=forms.CheckboxSelectMultiple(),
    method='category_method',
    label='Катеории'
  )
    

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.qs.prefetch_related('category', 'supplier')
    self.form.helper = FormHelper(self.form)
    self.form.helper.form_id = 'mainproduct-filter'
    self.form.helper.form_method = 'GET'
    self.form.helper.attrs = {
      'hx-get':reverse_lazy('mainproducts'),
      'hx-target':'#mainproducts-table',
      'hx-swap':'outerHTML',
      'hx-trigger':'keyup, click',
    }
    self.form.helper.layout = Layout(
        Field('search', label_class='font-bold text-lg'),
        Field('category'),
        Submit('submit', 'Поиск', css_class='mt-4')
    )
    
  def _build_partial_query(self, value):
      value = re.sub(r"[^\w\-\\\/]+", " ", value, flags=re.UNICODE)
      terms = [bit for bit in value.split() if bit]
      if not terms:
        return None
      query = SearchQuery('')
      for term in terms:
        query &= SearchQuery(f'{term}:*', search_type='raw', config='russian')
      return query
  def search_method(self, queryset, name, value):
    query = self._build_partial_query(value)
    if query is None:
      return queryset
    rank = SearchRank("search_vector", query)
    return queryset.annotate(rank=rank).filter(search_vector=query).order_by("-rank")
  def category_method(self, queryset, name, value):
    if list(value) == []:
      return queryset.filter(category__isnull=True)
    query = Q()
    for category in value:
      query |= Q(pk__in=category.get_descendants(include_self=True))
    categories = Category.objects.filter(query)
    return queryset.filter(category__in=categories)