from django import forms
from django.urls import reverse

from supplier_product_manager.models import Supplier, Setting, LINKS, SupplierFile


from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML


# # Формы для редактирования/создания настроек
# class SettingForm(forms.ModelForm):
#   sheet_name = forms.ChoiceField(label='Лист')
#   supplier = forms.ModelChoiceField(
#     Supplier.objects,
#     label='',
#     widget=forms.HiddenInput,
#     required=False
#   )
#   class Meta:
#     model = Setting
#     fields = '__all__'


class DictForm(forms.Form):
  key = forms.CharField(label='', required=False, widget=forms.TextInput(attrs={'class':'w-100'}))
  value = forms.CharField(label='', required=False, widget=forms.TextInput(attrs={'class':'w-100'}))

class InitialForm(forms.Form):
  """Форма для задания начальных значений"""
  initial = forms.CharField(label='Начальное значение',
                            required=False,
                            empty_value='')
  
class UploadFileForm(forms.ModelForm):
  class Meta:
    model = SupplierFile
    fields = ['file', 'setting']


class SettingForm(forms.ModelForm):
  class Meta:
    model = Setting
    fields = ['name', 'sheet_name']

  sheet_name = forms.ChoiceField(required=False)
  
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.helper = FormHelper(self)
    self.helper.form_id = 'setting-form'
    self.helper.form_method = 'POST'
    self.helper.layout = Layout(
      Field('name', css_class="form-control mb-4"),
      Field('sheet_name', css_class="form-select mb-4"),
      Submit('action', 'Применить'),
    )

class LinkForm(forms.Form):
  class Meta:
    fields = ['key']
  key = forms.CharField(widget=forms.Select(choices=LINKS),
                         label='',
                         required=False,
                         initial=LINKS[''])
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.helper = FormHelper(self)
    self.helper.form_id = 'setting-form'
    self.helper.form_method = 'POST'
    self.helper.layout = Layout(
      Field('key', css_class="form-select mb-4")
    )