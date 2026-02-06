from django import forms
from django.urls import reverse
from django.utils.safestring import mark_safe

from supplier_product_manager.models import Supplier, Setting, LINKS, SupplierFile, Link


from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML, Button

import os
import pandas as pd

class DictForm(forms.Form):
  def __init__(self, *args, **kwargs):
    pk = kwargs.pop('pk', None)
    link = kwargs.pop('link', None)
    if not pk or not link: return
    super().__init__(*args, **kwargs)
    self.helper = FormHelper(self)
    self.helper.form_tag = False
    self.helper.layout = Layout( 
      Div(
        Div(
          Field('key', css_class="form-control"),
          css_class="col-4"
        ),
        Div(
          Field('value', css_class="form-control"),
          css_class="col-4"
        ),
        HTML(f'''<button onclick="submit" class="btn btn-danger col-1" name="action" value="delete-{self.prefix}"><i class="bi bi-trash-fill"></i></button>'''),
        css_class="row gap-1 mb-4"
      )
    )
  key = forms.CharField(label='', required=False, widget=forms.TextInput())
  value = forms.CharField(label='', required=False, widget=forms.TextInput())


DictFormset = forms.formset_factory(
  DictForm, 
  min_num=1,
  extra=0)

class InitialForm(forms.Form):
  """Форма для задания начальных значений"""
  def __init__(self, *args, **kwargs):
    pk = kwargs.pop('pk', None)
    if not pk: return
    super().__init__(*args, **kwargs)
    self.helper = FormHelper(self)
    self.helper.form_tag = False
    self.helper.layout = Layout(
      Div(
        Field('initial', css_class="form-control mb-4"),
        css_class="row col-5 gap-1"
      )
    )
  initial = forms.CharField(label='Начальное значение',
                            required=False,
                            empty_value='')
  
class UploadFileForm(forms.ModelForm):
  def __init__(self, **kwargs):
    pk = kwargs.pop('pk', None)
    if not pk: return None
    super().__init__(**kwargs)
    self.fields['setting'] = forms.ModelChoiceField(queryset=Setting.objects.filter(supplier=pk), empty_label='Новая настройка', required=False)
  class Meta:
    model = SupplierFile
    fields = ['file', 'setting']


class SettingForm(forms.ModelForm):
  class Meta:
    model = Setting
    fields = ['name', 'sheet_name', 'create_new']

  sheet_name = forms.ChoiceField(
    required=False,
    label='Название листа')
  create_new = forms.ChoiceField(
    label='Добавлять в ПП если нет',
    required=False, 
    choices=[(False, 'Не добавлять'), (True, 'Добавлять')])

  
  
  def __init__(self, *args, **kwargs):
    pk = kwargs.pop('pk', None)
    if not pk: return
    super().__init__(*args, **kwargs)
    self.helper = FormHelper(self)
    self.helper.form_tag = False
    self.helper.layout = Layout(
      Field('name', css_class="form-control mb-4"),
      Field('sheet_name', css_class="form-select mb-4"),
      Field('create_new', css_class="form-select mb-4"),
      HTML('''
        <div class="row p-2">
          <ul>
            <li>Для загрузки необходим столбец с артиклем и названием</li>
            <li>Если есть дубликаты продуктов, то обрабатывается только первый</li>
          </ul>
        </div>
      '''),
      Div(
        Div(
          Div(
            HTML(f'''<button onclick="submit" class="btn btn-primary" name="action" value="apply">Применить</button>'''),
            HTML(f'''<button onclick="submit" class="btn btn-secondary" name="action" value="upload">Загрузить</button>'''),
            css_class='input-group'
          ),
          css_class='col-6'
        ),
        HTML(f'''<button onclick="submit" class="btn btn-danger ms-auto col-3" name="action" value="delete">Удалить<i class="bi bi-trash-fill"></i></button>'''),
        css_class='row mt-4'
      )
    )

class LinkForm(forms.Form):
  class Meta:
    fields = ['key']
  key = forms.CharField(widget=forms.Select(choices=LINKS),
                         label='',
                         required=False,
                         initial=LINKS[''])
  def __init__(self, *args, **kwargs):
    columns = kwargs.pop('columns', None)
    if columns is None: return
    super().__init__(*args, **kwargs)
    self.name = columns[int(self.prefix.strip('link-'))]
    self.helper = FormHelper(self)
    self.helper.form_tag = False
    self.helper.layout = Layout(
      Field('key', css_class="form-select mb-4")
    )


LinkFormset = forms.formset_factory(
  LinkForm,
  extra=0
)
