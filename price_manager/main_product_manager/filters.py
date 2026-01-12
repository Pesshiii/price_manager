from django_filters import filters, FilterSet
from .models import Category, Supplier, Manufacturer, MainProduct
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Q


from django.urls import reverse_lazy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML
from crispy_forms.utils import TEMPLATE_PACK

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
    label='Категории'
  )

  category_search = filters.CharFilter(
    method='category_search_method',
    label='Категория',
    widget=forms.TextInput(
      attrs={
        'placeholder': 'Категории',
        'class': 'form-control mb-2'
      }
    )
  )

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.qs.prefetch_related('supplier', 'category')
    # self._apply_category_search_queryset
    self.form.helper = FormHelper(self.form)
    self.form.helper.form_id = 'mainproduct-filter'
    self.form.helper.form_method = 'GET'
    self.form.helper.attrs = {
      'hx-get':reverse_lazy('mainproducts'),
      'hx-target':'#mainproducts-table',
      'hx-swap':'outerHTML',
      'hx-trigger':'change',
    }
    self.form.helper.layout = Layout(
        Field('search', label_class='mt-2', css_class='mb-4'),
        Field('category', template='supplier/partials/category_filter_field.html'),
        Div(
          Submit('action', 'Поиск', css_class='btn-primary btn-md'),
          HTML(f'''<a href="{reverse_lazy('mainproducts-sync')}" class="btn btn-secondary btn-md">Обновить</a>'''),
          css_class='d-flex justify-content-center btn-group mt-4'
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
  
  def category_method(self, queryset, name, value):
    if list(value) == []:
      return queryset
    query = Q()
    for category in value:
      query |= Q(pk__in=category.get_descendants(include_self=True))
    categories = Category.objects.filter(query)
    return queryset.filter(category__in=categories)
  # def _apply_category_search_queryset(self):
  #   values = self.qs.values_list('category__pk', flat=True)
  #   matching_categories = Category.objects.filter(pk__in=values)
  #   if not matching_categories.exists():
  #     self.filters['category'].field.queryset = Category.objects.none()
  #     return
  #   matching_ids = set()
  #   for category in matching_categories:
  #     matching_ids = matching_ids.union(set(category.get_ancestors(include_self=True).values_list('pk', flat=True)))
  #   filtered_tree = Category.objects.filter(pk__in=matching_ids).order_by('tree_id', 'lft')
  #   self.filters['category'].field.queryset = filtered_tree