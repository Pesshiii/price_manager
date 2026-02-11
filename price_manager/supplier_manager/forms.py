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
    self.helper.layout = Layout(
      'name', 
      Div(
        Div('delivery_days_available', css_class='col-4'),
        Div('delivery_days_navailable', css_class='col-4'),
        css_class='row',
      ),
      Field('currency', css_class='form-select'),
      HTML('<hr class="my-4 border-secondary">'),
      Div(
        Div(
        Field('price_update_rate', css_class='form-select'), css_class="col-4"),
        Div(
        Field('stock_update_rate', css_class='form-select'),css_class="col-4"),
        css_class='row'
      ),
      HTML('<hr class="my-4 border-secondary">'),
      Div(
        Div(
        Field('msg_available', css_class='form-control'), css_class="col-4"),
        Div(
        Field('msg_navailable', css_class='form-control'),css_class="col-4"),
        css_class='row mb-4'
      ),
      Submit('action', 'Сохранить', title="Поиск", css_class='btn btn-primary col-5 mt-4 btn-lg')
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
