from django import forms
from .models import Supplier, Manufacturer, ManufacturerDict, Category
from django.urls import reverse_lazy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML

class SupplierForm(forms.ModelForm):
  class Meta:
    model = Supplier
    fields = [
      'name',
      'delivery_days_available',
      'delivery_days_navailable',
      'currency',
      'price_update_rate',
      'stock_update_rate',
      'msg_available',
      'msg_navailable',
    ]
  def __init__(self, *args, **kwargs):
    url = kwargs.pop('url', None)
    if not url: return None
    super().__init__(*args, **kwargs)
    self.helper = FormHelper(self)
    self.helper.form_method = 'POST'
    self.helper.label_class='mt-4'
    self.helper.attrs = {
      'hx-post':url,
      'hx-target':'#supplier-update',
      'hx-swap':'outerHTML',
      'hx-trigger':'submit',
    }
    action_buttons = [
      Submit('action', 'Сохранить', title="Сохранить", css_class='btn btn-primary btn-lg me-2')
    ]
    if self.instance and self.instance.pk:
      delete_url = reverse_lazy('supplier-delete', kwargs={'id': self.instance.pk})
      action_buttons.append(
        HTML(f'''
          <button type="button"
                  class="btn btn-outline-danger btn-lg"
                  data-bs-toggle="modal"
                  data-bs-target="#deleteSupplierModal">
            Удалить поставщика
          </button>
          <div class="modal fade" id="deleteSupplierModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
              <div class="modal-content">
                <div class="modal-header">
                  <h5 class="modal-title">Подтвердите удаление</h5>
                  <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                  Будут удалены товары поставщика и сам поставщик. Продолжить?
                </div>
                <div class="modal-footer">
                  <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                  <form method="post" action="{delete_url}">
                    <input type="hidden" name="csrfmiddlewaretoken" value="{{{{ csrf_token }}}}">
                    <button type="submit" class="btn btn-danger">Удалить</button>
                  </form>
                </div>
              </div>
            </div>
          </div>
        ''')
      )

    self.helper.layout = Layout(
      Div(
        Div('name', css_class='col-8'),
        css_class='row',
      ),
      Div(
        Div(
          Field('currency', css_class='form-select'), 
          css_class='col-8'
        ), 
        css_class='row'
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(
        Div(
        Field('price_update_rate', css_class='form-select'), css_class="col-4"),
        Div(
        Field('stock_update_rate', css_class='form-select'),css_class="col-4"),
        css_class='row'
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(
        Div('delivery_days_available', css_class='col-4'),
        Div('delivery_days_navailable', css_class='col-4'),
        css_class='row',
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(
        Div(
        Field('msg_available', css_class='form-control'), css_class="col-4"),
        Div(
        Field('msg_navailable', css_class='form-control'),css_class="col-4"),
        css_class='row mb-4'
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(*action_buttons, css_class='d-flex align-items-center gap-2 mt-4')
    )

class ManufacturerDictForm(forms.ModelForm):
  manufacturer = forms.ModelChoiceField(Manufacturer.objects,
                                        label='',
                                        widget=forms.HiddenInput())
  class Meta:
    model = ManufacturerDict
    fields = '__all__'

class CategoryAddForm(forms.Form):
  # Используется при связке категории с товарами
  category = forms.ModelChoiceField(
    Category.objects,
    label='Категория',
    widget=forms.Select(attrs={
      'class':'form-select'
    })
  )
