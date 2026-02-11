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
    fields = ['search', 'category']

  search = filters.CharFilter(
    method='search_method',
    label='Поиск',
    widget=forms.TextInput(
       attrs={
          'placeholder': 'Поиск...'
       }
    )
  )

  supplier_search = filters.CharFilter(
        method='nothing_search',
        label='Поставщики',
        widget=forms.TextInput(attrs={
            'placeholder': 'Поиск поставщиков...',
        })
    )

  supplier = filters.ModelMultipleChoiceFilter(
    label='',
    field_name='supplier',
    queryset=Supplier.objects.none(),
    widget=forms.widgets.CheckboxSelectMultiple(
      attrs={'class':'form-check'},
    )
    )

  manufacturer_search = filters.CharFilter(
        method='nothing_search',
        label='Производители',
        widget=forms.TextInput(attrs={
            'placeholder': 'Поиск производителей...',
        })
    )

  manufacturer = filters.ModelMultipleChoiceFilter(
    label='',
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
      'hx-trigger':'change',
    }
    self.form.helper.layout = Layout(
        'search',
        Field('supplier_search'),
        Field('supplier', template='supplier/partials/checkbox_filter_field.html'),
        Field('manufacturer_search'),
        Field('manufacturer', template='supplier/partials/checkbox_filter_field.html'),
        Field('category', template='supplier/partials/category_filter_field.html'),
        Div(
          Submit('action', 'Поиск', title="Поиск", css_class='btn btn-primary col-5  btn-lg'),
          HTML('''<a href="{% url 'mainproducts' %}" class="btn btn-secondary col-4 btn-lg" title="Сбросить">Сбросить</a>'''),
          css_class='d-flex gap-1 mt-4 container'
        )
    )

  def config_filters(self, queryset):

    supplier_search_term = self.data.get('supplier_search', '')
    sq = Q(pk__in=queryset.values('supplier'))
    if not supplier_search_term == '':
      sq &= Q(name__icontains=supplier_search_term)
    if not self.data.getlist('supplier') == []:
      self.filters['supplier'].field.queryset = Supplier.objects.filter(
        Q(pk__in=Supplier.objects.filter(sq)[:10])|Q(pk__in=self.data.getlist('supplier', None))
        )
    else:  
      self.filters['supplier'].field.queryset = Supplier.objects.filter(
        Q(pk__in=Supplier.objects.filter(sq)[:10])
        )
    

    manufacturer_search_term = self.data.get('manufacturer_search', '')
    mq = Q(pk__in=queryset.values('manufacturer'))
    if not manufacturer_search_term == '':
      mq &= Q(
          name__icontains=manufacturer_search_term
      )
    if not self.data.getlist('manufacturer') == []:
      self.filters['manufacturer'].field.queryset = Manufacturer.objects.filter(
        Q(pk__in=Manufacturer.objects.filter(mq)[:10])|Q(pk__in=self.data.getlist('manufacturer', None))
        )
    else:  
      self.filters['manufacturer'].field.queryset = Manufacturer.objects.filter(
        Q(pk__in=Manufacturer.objects.filter(mq)[:10])
        )
      
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
  
  def nothing_search(self, queryset, name, value):
      # This method just stores the search term for filtering suppliers
      # The actual filtering is done by filter_supplier_choice
      return queryset

  def category_method(self, queryset, name, value):
    if list(value) == []:
      return queryset
    query = Q()
    for category in value:
      query |= Q(pk__in=category.get_descendants(include_self=True))
    categories = Category.objects.filter(query)
    return queryset.filter(category__in=categories)
