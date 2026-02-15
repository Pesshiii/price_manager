
from django_filters import filters, FilterSet
from .models import SupplierProduct
from django import forms
from django.urls import reverse_lazy, reverse
from django.utils.safestring import mark_safe


from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML


class SupplierProductFilter(FilterSet):
  class Meta:
    model = SupplierProduct
    fields = ['name', 'is_tied']
  name = filters.CharFilter(field_name='name', lookup_expr='icontains')
  is_tied = filters.BooleanFilter(field_name='main_product', label='Есть связь с ГП', lookup_expr='isnull', exclude=True)
  def __init__(self, *args, **kwargs):
    pk = kwargs.pop('pk', None)
    super().__init__(*args, **kwargs)
    # self.qs.prefetch_related('supplier', 'category')
    # self._apply_category_search_queryset
    self.form.helper = FormHelper(self.form)
    self.form.helper.form_id = 'supplierproduct-filter'
    self.form.helper.form_method = 'GET'
    self.form.helper.attrs = {
      'hx-get':reverse('supplier-detail', kwargs={'pk': pk}),
      'hx-target':'#products',
      'hx-swap':'innerHTML',
      'hx-trigger':'submit, change',
      'hx-push-url':"true",
      'class': 'card p-3',
    }
    self.form.helper.layout = Layout(
        Field('name', label_class='mt-2', css_class='mb-4'),
        Field('is_tied', css_class="form-select mb-4"),
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
          css_class='d-flex justify-content-center btn-group mt-4'
        )
    )