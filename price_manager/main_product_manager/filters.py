from django_filters import filters, FilterSet
from .models import Category, Supplier, Manufacturer, MainProduct
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Q


from django.urls import reverse_lazy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML

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

  available = filters.BooleanFilter(
    label='Товары в наличии',
    method='available_method',
    widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
  )

  supplier = filters.ModelMultipleChoiceFilter(
    label='Поставщики',
    field_name='supplier',
    queryset=Supplier.objects.none(),
    widget=forms.widgets.CheckboxSelectMultiple(
      attrs={'class':'form-check'},
    )
    )

  manufacturer = filters.ModelMultipleChoiceFilter(
    label='Производители',
    field_name='manufacturer',
    queryset=Manufacturer.objects.none(),
    widget=forms.widgets.CheckboxSelectMultiple(
      attrs={'class':'form-check'},
    )
    )

  category = filters.ModelMultipleChoiceFilter(
    queryset=Category.objects.all(),
    widget=forms.CheckboxSelectMultiple(),
    method='category_method',
    label='Категории'
  )

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.config_filters(self.search_method(self.queryset, '', value=self.data.get('search', '')))
    self.form.helper = FormHelper(self.form)
    self.form.helper.form_id = 'mainproduct-filter'
    self.form.helper.form_method = 'GET'
    self.form.helper.label_class='mt-2'
    self.form.helper.attrs = {
      'hx-get':reverse_lazy('mainproducts'),
      'hx-target':'#mainproducts-block',
      'hx-swap':'outerHTML',
      'hx-trigger':'input changed delay:1s, submit',
    }
    self.form.helper.layout = Layout(
        HTML('<h5 class="mb-3">Фильтры товаров</h5>'),
        Div(
          Field('search'),
          css_class='mb-3'
        ),
        Div(
          Field('available'),
          css_class='border rounded p-3 bg-body-tertiary mb-3'
        ),
        Div(
          Field('supplier', template='supplier/partials/checkbox_filter_field.html'),
          css_class='border rounded p-3 bg-body-tertiary mb-3'
        ),
        Div(
          Field('manufacturer', template='supplier/partials/checkbox_filter_field.html'),
          css_class='border rounded p-3 bg-body-tertiary mb-3'
        ),
        Div(
          Field('category', template='supplier/partials/category_filter_field.html'),
          css_class='border rounded p-3 bg-body-tertiary'
        ),
        Div(
          Submit('action', 'Применить', title="Применить", css_class='btn btn-primary flex-grow-1'),
          HTML("""<a href=\"{% url 'mainproducts' %}\" class=\"btn btn-outline-secondary\" title=\"Сбросить\">Сбросить</a>"""),
          css_class='d-flex gap-2 mt-4'
        )
    )

  def config_filters(self, queryset):
    selected_suppliers = self.data.getlist('supplier', None)
    supplier_queryset = Supplier.objects.filter(pk__in=queryset.values('supplier')).order_by('name')
    if selected_suppliers:
      supplier_queryset = Supplier.objects.filter(
        Q(pk__in=supplier_queryset.values('pk')) | Q(pk__in=selected_suppliers)
      ).order_by('name')
    self.filters['supplier'].field.queryset = supplier_queryset

    selected_manufacturers = self.data.getlist('manufacturer', None)
    manufacturer_queryset = Manufacturer.objects.filter(pk__in=queryset.values('manufacturer')).order_by('name')
    if selected_manufacturers:
      manufacturer_queryset = Manufacturer.objects.filter(
        Q(pk__in=manufacturer_queryset.values('pk')) | Q(pk__in=selected_manufacturers)
      ).order_by('name')
    self.filters['manufacturer'].field.queryset = manufacturer_queryset

    return None


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

  def available_method(self, queryset, name, value):
    if value:
      return queryset.filter(stock__gt=0)
    return queryset

  def category_method(self, queryset, name, value):
    if list(value) == []:
      return queryset
    query = Q()
    for category in value:
      query |= Q(pk__in=category.get_descendants(include_self=True))
    categories = Category.objects.filter(query)
    return queryset.filter(category__in=categories)
