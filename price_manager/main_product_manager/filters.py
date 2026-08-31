from django_filters import filters, FilterSet
from .models import Category, Supplier, Manufacturer, MainProduct
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Q, Case, When, Value, IntegerField


from django.urls import reverse_lazy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML, Hidden
from core.crispy_fields import CustomCheckbox, OobField

import re

class MainProductFilter(FilterSet):
  class Meta:
    model = MainProduct
    fields = ['search', 'categories', 'available']

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

  categories = filters.ModelMultipleChoiceFilter(
    queryset=Category.objects.all(),
    widget=forms.CheckboxSelectMultiple(),
    method='categories_method',
    label='Категории'
  )

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.config_filters(self.search_method(self.queryset, '', value=self.data.get('search', '')))

  def build_helper(self, url, hx_target: str | None = '#mainproducts-table', stripped=False):
    """Builds the crispy FormHelper/Layout for rendering the filter form.

    Only needed by a view that actually renders mainproduct/partials/filter.html
    (MainProductFilterView, ResolveMainproduct) — other callers only need `.qs`, so
    this is kept out of __init__ to avoid paying for it on every filterset instantiation.

    `stripped=True` renders just the filter fields with no <form> tag, header, or
    submit button — used by ResolveMainproduct when re-embedding the form inside an
    htmx-swapped table fragment that must stay bound to the same GET params.
    """
    helper = FormHelper(self.form)
    helper.form_id = 'mainproduct-filter'
    helper.form_method = 'GET'
    helper.label_class = 'mt-2'
    helper.attrs = {
      'hx-get':url,
      'hx-swap':'outerHTML',
      'hx-trigger':'input changed delay:2s, change delay:2s, submit',
      'hx-push-url':'true',
      'hx-include':'#mainproducts-search',
    }
    if hx_target:
      helper.attrs['hx-target']=hx_target
    if stripped:
      helper.form_tag = False
      helper.layout = Layout(
          OobField('categories', template='supplier/partials/category_filter_field.html'),
          OobField('supplier', template='core/includes/checkbox_field.html#checkboxes'),
          OobField('manufacturer', template='core/includes/checkbox_field.html#checkboxes'),)
    else:
      helper.layout = Layout(
          Hidden('bound', 'true'),
          HTML('''
            <div class="filter-header d-flex align-items-center gap-2 mb-3">
              <i class="bi bi-sliders text-primary"></i>
              <h5 class="mb-0">Фильтры товаров</h5>
            </div>
          '''),
          Div(
            Field('available', template='core/includes/switch_field.html'),
            css_class='filter-section'
          ),
          Div(
            Field('categories', template='supplier/partials/category_filter_field.html'),
            css_class='filter-section'
          ),
          Div(
            Field('supplier', template='core/includes/checkbox_field.html'),
            css_class='filter-section'
          ),
          Div(
            Field('manufacturer', template='core/includes/checkbox_field.html'),
            css_class='filter-section filter-section-last'
          ),
          Div(
            Submit('action', 'Применить', title="Применить", css_class='btn btn-primary flex-grow-1'),
            HTML(f"""<a href=\"{url}\" class=\"btn btn-outline-secondary\" title=\"Сбросить\"><i class="bi bi-arrow-counterclockwise"></i></a>"""),
            HTML('''<button type="button" class="btn btn-outline-secondary" id="filter-scroll-top-btn" title="Наверх" data-ignore-auto-update="true"><i class="bi bi-arrow-up"></i></button>'''),
            css_class='d-flex gap-2 filter-actions'
          )
      )
    self.form.helper = helper
    return helper

  def config_filters(self, queryset):
    selected_suppliers = self.data.getlist('supplier', None)
    supplier_queryset = Supplier.objects.filter(pk__in=queryset.values('supplier')).order_by('name')
    if selected_suppliers:
      supplier_queryset = Supplier.objects.filter(
        Q(pk__in=supplier_queryset) | Q(pk__in=selected_suppliers)
      ).annotate(
        is_selected=Case(
          When(pk__in=selected_suppliers, then=Value(0)),
          default=Value(1),
          output_field=IntegerField(),
        )
      ).order_by('is_selected', 'name')
    self.filters['supplier'].field.queryset = supplier_queryset

    selected_manufacturers = self.data.getlist('manufacturer', None)
    manufacturer_queryset = Manufacturer.objects.filter(pk__in=queryset.values('manufacturer')).order_by('name')
    if selected_manufacturers:
      manufacturer_queryset = Manufacturer.objects.filter(
        Q(pk__in=manufacturer_queryset) | Q(pk__in=selected_manufacturers)
      ).annotate(
        is_selected=Case(
          When(pk__in=selected_manufacturers, then=Value(0)),
          default=Value(1),
          output_field=IntegerField(),
        )
      ).order_by('is_selected', 'name')
    self.filters['manufacturer'].field.queryset = manufacturer_queryset

    category_queryset = Category.objects.filter(pk__in=queryset.values('categories')).get_ancestors(include_self=True)
    selected_categories = Category.objects.filter(pk__in=self.data.getlist('categories', None))
    if selected_categories:
      category_queryset = Category.objects.filter(Q(pk__in=category_queryset)|Q(pk__in=selected_categories))

    self.filters['categories'].field.queryset = category_queryset

    return None

  def _get_terms(self, value):
    # value = re.sub(r"[^\w\-\\\/]+|_", " ", value, flags=re.UNICODE)
    return [term for term in value.split() if term]
  def _build_partial_query(self, value):
    terms = self._get_terms(value)
    if not terms:
      return None
    query = Q()
    for term in terms:
      query &= (Q(sku__icontains=term)|Q(name__icontains=term)|Q(article__icontains=term))
    return query

  def search_method(self, queryset, name, value):
    query = self._build_partial_query(value)
    if query is None:
      return queryset
    search_query = SearchQuery(value, config='russian')
    rank = SearchRank("search_vector", search_query)
    return queryset.annotate(rank=rank).filter(Q(search_vector=search_query)|query).order_by("-rank")

  def available_method(self, queryset, name, value):
    if value:
      return queryset.filter(stock__gt=0)
    return queryset

  def categories_method(self, queryset, name, value):
    if list(value) == []:
      return queryset
    query = Q()
    for category in value:
      query |= Q(pk__in=category.get_descendants(include_self=True))
    categories = Category.objects.filter(query)
    return queryset.filter(categories__in=categories).distinct()
