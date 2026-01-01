from django import forms
from .models import Supplier, Manufacturer, ManufacturerDict, Category

class SupplierForm(forms.ModelForm):
  class Meta:
    model = Supplier
    fields = ['name', 'delivery_days', 'currency', 'price_update_rate', 'stock_update_rate', 'msg_available', 'msg_navailable']

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
