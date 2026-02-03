from django import forms
from django.urls import reverse
from django.utils.safestring import mark_safe

from supplier_product_manager.models import Supplier, Setting, LINKS, SupplierFile, Link


from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML, Button

import os
import pandas as pd

def get_df_sheet_names(pk):
  file = None
  file = SupplierFile.objects.filter(setting=pk).first().file
  if not file: return None
  columns = pd.ExcelFile(file, engine='calamine').sheet_names
  file.close()
  return columns

def get_df(pk, nrows: int | None = 100):
  file = None
  setting = Setting.objects.get(pk=pk)

  file = SupplierFile.objects.filter(setting=pk).first().file
  if not file: return None
  df = pd.read_excel(file, engine='calamine', sheet_name=setting.sheet_name, nrows=nrows, index_col=None).dropna(axis=0, how='all').dropna(axis=1, how='all')
  file.close()
  if df.shape[0] == 0:
    return None
  return df

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

def get_dictformset(post, pk, link):
  
  mlink = Link.objects.get_or_create(setting=pk, key=link)[0]
  return DictFormset(
          post if post else None,
          initial=[
            {'key': ldict.key, 'value': ldict.value}
            for ldict in mlink.dicts.all()
          ],
          form_kwargs={'link':link, 'pk':pk},
          prefix=f'{link}-dict'
        )
  
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
    fields = ['name', 'sheet_name']

  sheet_name = forms.ChoiceField(required=False)
  
  def __init__(self, *args, **kwargs):
    pk = kwargs.pop('pk', None)
    if not pk: return
    super().__init__(*args, **kwargs)
    self.helper = FormHelper(self)
    self.helper.form_tag = False
    self.helper.layout = Layout(
      Field('name', css_class="form-control mb-4"),
      Field('sheet_name', css_class="form-select mb-4"),
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
        css_class='row'
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

def get_linkformset(post, pk):
  df = get_df(pk)
  if df is None: return None
  setting = Setting.objects.get(pk=pk)
  return LinkFormset(
      post if post else None, 
      initial=[
          {
            'key': 
            Link.objects.filter(setting=setting, value=column).first().key 
            if Link.objects.filter(setting=setting, value=column).exists()
            else None
          }

          for column in df.columns
        ],
      prefix='link', 
      form_kwargs=
        {
          'columns':df.columns
        }
      )


def get_indicts(post, pk):
  indicts = dict()
  for link, name in LINKS.items():
    if link == '': continue
    mlink = Link.objects.get_or_create(setting=Setting.objects.get(pk=pk), key=link)[0]
    dict_formset = DictFormset(
          post if post else None,
          initial=[
            {'key': ldict.key, 'value': ldict.value}
            for ldict in mlink.dicts.all()
          ],
          form_kwargs={'link':link, 'pk':pk},
          prefix=f'{link}-dict'
        )
    initial = InitialForm(post, initial=mlink.initial, prefix=f'{link}-initial', pk=pk)
    indicts[link] = (initial, dict_formset)
    if post and dict_formset.is_valid() and post.get('action'):
      action = post.get('action')
      if 'delete-' + link in action:
        data = []
        for i in range(len(dict_formset.cleaned_data)):
          if not i == int(action.strip(f'delete-{link}-dict-')):
            data.append(dict_formset.cleaned_data[i])
        dict_formset = DictFormset(initial=data,
                        form_kwargs={'link':link, 'pk':pk},
                        prefix=f'{link}-dict')
      elif 'add-' + link in action:
        data = dict_formset.cleaned_data
        data.append({})
        dict_formset = DictFormset(initial=data,
                        form_kwargs={'link':link, 'pk':pk},
                        prefix=f'{link}-dict')
    indicts[link] = { 
        'verbose_name':name, 
        'initial':initial, 
        'dict_formset':dict_formset,
        }
  return indicts