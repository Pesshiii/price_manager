from django_filters import filters, FilterSet
from .models import Category, Supplier, Manufacturer, MainProduct
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Q


from django.urls import reverse_lazy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML, Hidden
from core.crispy_fields import CustomCheckbox

import re

class MainProductFilter(FilterSet):
  class Meta:
    model = MainProduct
    fields = ['search', 'category', 'available']

  search = filters.CharFilter(
    method='search_method',
    label='Поиск товаров',
    widget=forms.TextInput(
       attrs={
          'placeholder': 'Название, артикул или ключевое слово',
          'class': 'form-control',
       }
    )
  )

  def __init__(self, *args, url=None, bound_ignore=False, hx_target:str|None='#mainproducts-table', **kwargs):
    super().__init__(*args, **kwargs)
    self.form.helper = FormHelper(self.form)
    self.form.helper.form_id = 'mainproduct-filter'
    self.form.helper.form_method = 'GET'
    self.form.helper.label_class='mt-2'
    self.form.helper.attrs = {
      'hx-get':url,
      'hx-swap':'innerHTML',
      'hx-trigger':'input changed delay:2s, change delay:2s, submit',
      'hx-push-url':'true'
    }
    if hx_target:
      self.form.helper.attrs['hx-target']=hx_target
    if not self.data.get('bound', None) or bound_ignore:
      self.form.helper.layout = Layout(
          Hidden('bound', 'true'),
          HTML('<h5 class="mb-3">Фильтры товаров</h5>'),
          Div(
            Field('search'),
            css_class='mb-3'
          ),
          HTML('<hr class="border-secondary">'),
          Div(
            Submit('action', 'apply', title="Применить", css_class='btn btn-primary flex-grow-1'),
            Submit('action', 'default', title="Сбросить", css_class='btn btn-secondary flex-grow-1'),
          )
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