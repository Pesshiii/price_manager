from django import forms
from supplier_product_manager.models import Supplier, Setting, LINKS

# Формы для редактирования/создания настроек
class SettingForm(forms.ModelForm):
  sheet_name = forms.ChoiceField(label='Лист')
  supplier = forms.ModelChoiceField(
    Supplier.objects,
    label='',
    widget=forms.HiddenInput,
    required=False
  )
  class Meta:
    model = Setting
    fields = '__all__'

class LinkForm(forms.Form):
  """Форма для связки в Link"""
  key = forms.CharField(widget=forms.Select(choices=LINKS),
                         label='',
                         required=False,
                         initial=LINKS[''])
  value = forms.CharField(label='', widget=forms.HiddenInput)
  class Meta:
    fields = ['key', 'value']

class DictForm(forms.Form):
  key = forms.CharField(label='', required=False, widget=forms.TextInput(attrs={'class':'w-100'}))
  value = forms.CharField(label='', required=False, widget=forms.TextInput(attrs={'class':'w-100'}))

class InitialForm(forms.Form):
  """Форма для задания начальных значений"""
  initial = forms.CharField(label='Начальное значение',
                            required=False,
                            empty_value='')
