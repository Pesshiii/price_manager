from django import forms
from django.db.models import Q
from django.urls import reverse
from django_filters import FilterSet, filters
from django_filters.widgets import RangeWidget

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Field, HTML, Layout, Submit

from supplier_manager.models import Category, Discount, Manufacturer

from .models import SupplierProduct


class SupplierProductFilter(FilterSet):
  article = filters.CharFilter(field_name='article', lookup_expr='icontains', label='Артикул')
  name = filters.CharFilter(field_name='name', lookup_expr='icontains', label='Название')
  description = filters.CharFilter(field_name='description', lookup_expr='icontains', label='Описание')

  category = filters.ModelMultipleChoiceFilter(
    field_name='category',
    queryset=Category.objects.none(),
    label='Категория',
    widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
  )
  manufacturer = filters.ModelMultipleChoiceFilter(
    field_name='manufacturer',
    queryset=Manufacturer.objects.none(),
    label='Производитель',
    widget=forms.widgets.CheckboxSelectMultiple(),
  )
  discount = filters.ModelMultipleChoiceFilter(
    field_name='discount',
    queryset=Discount.objects.none(),
    label='Группа скидок',
    widget=forms.widgets.CheckboxSelectMultiple(),
  )

  stock_min = filters.NumberFilter(field_name='stock', lookup_expr='gte', label='Остаток от')
  stock_max = filters.NumberFilter(field_name='stock', lookup_expr='lte', label='Остаток до')
  supplier_price_min = filters.NumberFilter(field_name='supplier_price', lookup_expr='gte', label='Цена поставщика от')
  supplier_price_max = filters.NumberFilter(field_name='supplier_price', lookup_expr='lte', label='Цена поставщика до')
  rrp_min = filters.NumberFilter(field_name='rrp', lookup_expr='gte', label='РРЦ от')
  rrp_max = filters.NumberFilter(field_name='rrp', lookup_expr='lte', label='РРЦ до')
  discount_price_min = filters.NumberFilter(field_name='discount_price', lookup_expr='gte', label='Цена со скидкой от')
  discount_price_max = filters.NumberFilter(field_name='discount_price', lookup_expr='lte', label='Цена со скидкой до')

  updated_at = filters.DateFromToRangeFilter(
    field_name='updated_at',
    label='Обновлено',
    widget=RangeWidget(attrs={'type': 'date', 'class': 'form-control'}),
  )
  is_tied = filters.BooleanFilter(
    field_name='main_product',
    label='Связан с ГП',
    lookup_expr='isnull',
    exclude=True,
    widget=forms.Select(
      choices=[('', '---------'), ('true', 'Да'), ('false', 'Нет')],
      attrs={'class': 'form-select'},
    ),
  )

  class Meta:
    model = SupplierProduct
    fields = [
      'article',
      'name',
      'description',
      'category',
      'manufacturer',
      'discount',
      'stock_min',
      'stock_max',
      'supplier_price_min',
      'supplier_price_max',
      'rrp_min',
      'rrp_max',
      'discount_price_min',
      'discount_price_max',
      'updated_at',
      'is_tied',
    ]

  def __init__(self, *args, **kwargs):
    pk = kwargs.pop('pk', None)
    super().__init__(*args, **kwargs)

    queryset = self.queryset
    if pk:
      queryset = queryset.filter(supplier_id=pk)

    self._setup_related_queryset(
      filter_name='category',
      model=Category,
      ids_key='category',
      queryset=self._apply_current_filters(queryset, excluded_key='category'),
    )
    self._setup_related_queryset(
      filter_name='manufacturer',
      model=Manufacturer,
      ids_key='manufacturer',
      queryset=self._apply_current_filters(queryset, excluded_key='manufacturer'),
    )
    self._setup_related_queryset(
      filter_name='discount',
      model=Discount,
      ids_key='discount',
      queryset=self._apply_current_filters(queryset, excluded_key='discount'),
    )

    self.form.helper = FormHelper(self.form)
    self.form.helper.form_id = 'supplierproduct-filter'
    self.form.helper.form_method = 'GET'
    self.form.helper.attrs = {
      'hx-get': reverse('supplier-detail', kwargs={'pk': pk}),
      'hx-target': '#products',
      'hx-swap': 'innerHTML',
      'hx-trigger': 'submit, change',
      'hx-push-url': 'true',
      'class': 'card p-3',
    }
    self.form.helper.layout = Layout(
      HTML('<details class="mb-3" open><summary class="fw-semibold mb-2">Текстовые поля</summary>'),
      Div(
        Field('article', label_class='mt-2'),
        Field('name', label_class='mt-2'),
        Field('description', label_class='mt-2'),
        css_class='mb-3',
      ),
      HTML('</details>'),
      HTML('<details class="mb-3" open><summary class="fw-semibold mb-2">Справочники</summary>'),
      Div(
        Field('category', template='supplier/partials/category_filter_field.html'),
        Field('manufacturer', template='core/includes/checkbox_field.html'),
        Field('discount', template='core/includes/checkbox_field.html'),
        Field('is_tied', css_class='form-select'),
        css_class='mb-3',
      ),
      HTML('</details>'),
      HTML('<details class="mb-3" open><summary class="fw-semibold mb-2">Числовые значения</summary>'),
      Div(
        Div(Field('stock_min'), Field('stock_max'), css_class='row d-flex flex-column gap-2'),
        Div(Field('supplier_price_min'), Field('supplier_price_max'), css_class='row d-flex flex-column gap-2'),
        Div(Field('rrp_min'), Field('rrp_max'), css_class='row d-flex flex-column gap-2'),
        Div(Field('discount_price_min'), Field('discount_price_max'), css_class='row d-flex flex-column gap-2'),
        css_class='row g-2 mb-3',
      ),
      HTML('</details>'),
      HTML('<details class="mb-3" open><summary class="fw-semibold mb-2">Дата обновления</summary>'),
      Div(
        Field('updated_at'),
        css_class='mb-3',
      ),
      HTML('</details>'),
      Div(
        Submit('action', 'Поиск', css_class='btn btn-primary btn-md'),
        HTML('''
            <button type="button"
                    class="btn btn-md btn-secondary"
                    title="Загрузка"
                    data-bs-toggle="modal"
                    data-bs-target="#modal-container"
                    hx-get="{% url 'supplier-copymain' supplier.pk 0%}{% querystring %}"
                    hx-target="#modal-container .modal-content"
                    hx-swap="innerHTML">
              <span>Копировать в ГП</span>
            </button>'''),
        css_class='d-flex justify-content-center btn-group mt-4',
      ),
    )

  def _setup_related_queryset(self, filter_name, model, ids_key, queryset):
    selected_ids = self.data.getlist(ids_key)
    base_queryset = model.objects.filter(pk__in=queryset.values(ids_key)).distinct().order_by('name')
    if selected_ids:
      base_queryset = model.objects.filter(Q(pk__in=base_queryset) | Q(pk__in=selected_ids)).distinct().order_by('name')
    self.filters[filter_name].field.queryset = base_queryset

  def _apply_current_filters(self, queryset, excluded_key=None):
    data = self.data

    def get_value(name):
      if excluded_key == name:
        return None
      value = data.get(name)
      return value.strip() if isinstance(value, str) else value

    def get_list(name):
      if excluded_key == name:
        return []
      return [value for value in data.getlist(name) if value]

    for field_name in ('article', 'name', 'description'):
      value = get_value(field_name)
      if value:
        queryset = queryset.filter(**{f'{field_name}__icontains': value})

    for relation in ('category', 'manufacturer', 'discount'):
      ids = get_list(relation)
      if ids:
        queryset = queryset.filter(**{f'{relation}__in': ids})

    range_filters = (
      ('stock', 'stock_min', 'stock_max'),
      ('supplier_price', 'supplier_price_min', 'supplier_price_max'),
      ('rrp', 'rrp_min', 'rrp_max'),
      ('discount_price', 'discount_price_min', 'discount_price_max'),
    )
    for field_name, min_name, max_name in range_filters:
      min_value = get_value(min_name)
      max_value = get_value(max_name)
      if min_value:
        queryset = queryset.filter(**{f'{field_name}__gte': min_value})
      if max_value:
        queryset = queryset.filter(**{f'{field_name}__lte': max_value})

    updated_after = get_value('updated_at_after')
    updated_before = get_value('updated_at_before')
    if updated_after:
      queryset = queryset.filter(updated_at__date__gte=updated_after)
    if updated_before:
      queryset = queryset.filter(updated_at__date__lte=updated_before)

    is_tied = get_value('is_tied')
    if is_tied == 'true':
      queryset = queryset.filter(main_product__isnull=False)
    elif is_tied == 'false':
      queryset = queryset.filter(main_product__isnull=True)

    return queryset
