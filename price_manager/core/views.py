# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404,
                              HttpResponse,
)
from django.utils import timezone
from django.http import HttpResponseRedirect, HttpResponse
from django.template.loader import render_to_string
from django.contrib import messages
from django.views.generic import (View,
                                  ListView,
                                  DetailView,
                                  CreateView,
                                  UpdateView,
                                  DeleteView,
                                  FormView,
                                  TemplateView)
from django.views.decorators.http import require_POST
from django.urls import reverse
from typing import Optional, Any, Dict, Iterable
from django.shortcuts import redirect, render
from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView, FilterMixin
from decimal import Decimal, InvalidOperation

# Импорты моделей, функций, форм, таблиц
from .models import *
from .functions import *
from .forms import *
from .tables import *
from .filters import *

# Импорты сторонних библиотек
import pandas as pd
import re
import math
import datetime
import time
import time


@require_POST
def toggle_basket(request, pk):
    basket = request.session.setdefault('basket', [])
    pk = int(pk)

    if pk in basket:
        basket.remove(pk)
    else:
        basket.append(pk)

    request.session.modified = True

    # return only the fresh button
    html = render_to_string(
        'main/product/actions.html',
        {
            'record': get_object_or_404(MainProduct, pk=pk),
            'basket': basket,
        },
        request=request
    )
    return HttpResponse(html)

class MainPage(SingleTableMixin, FilterView):
  model = MainProduct
  filterset_class = MainProductFilter
  table_class = MainProductListTable
  template_name = 'main/main.html'
  def get_table(self, **kwargs):
    return super().get_table(**kwargs, request=self.request)
  def get_context_data(self, **kwargs):
    # Чистка базы файлов
    context = super().get_context_data(**kwargs)
    try:
      for file in FileModel.objects.all():
        file.file.delete()
        file.delete()
    except BaseException as ex:
      messages.error(self.request, f'{ex}')
    return context

# Обработка поставщика

class SupplierList(SingleTableView):
  '''Список поставщиков на <<supplier/>>'''
  model = Supplier
  table_class = SupplierListTable
  template_name = 'supplier/list.html'

class SupplierSettingList(SingleTableView):
  '''Список Настроек на транице <<supplier/<int:id>/settings/>>'''
  model = Setting
  table_class = SettingListTable
  template_name = 'supplier/settings.html'
  def get_table_data(self):
    return Setting.objects.filter(supplier_id=self.kwargs['id'])
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['supplier_id'] = self.kwargs['id']
    context['supplier'] = Supplier.objects.get(id=context['supplier_id'])
    return context
  
class SupplierDetail(SingleTableMixin, FilterView):
  '''
  Таблица отображения товаров на странице поставщиков
  <<supplier/<int:id>/>>
  '''

  model = SupplierProduct
  table_class = SupplierProductListTable
  filterset_class = SupplierProductFilter
  template_name = 'supplier/detail.html'

  def get_table_data(self):
    return super().get_table_data().filter(supplier=self.kwargs.get('id', None))
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['supplier'] = Supplier.objects.get(id=self.kwargs.get('id'))
    return context


class SupplierCreate(CreateView):
  '''Таблица создания Поставщиков <<supplier/create/>>'''
  model = Supplier
  fields = ['name', 'delivery_days']
  success_url = '/supplier'
  template_name = 'supplier/create.html'

class SupplierDelete(DeleteView):
  model = Supplier
  success_url = '/supplier/'
  pk_url_kwarg = 'id'
  template_name = 'supplier/confirm_delete.html'

class SupplierUpdate(UpdateView):
  '''Таблица  обновления Поставщиков <<supplier/update/>>'''
  model = Supplier
  fields = '__all__'
  success_url = '/supplier'
  template_name = 'supplier/update.html'
  pk_url_kwarg='id'


# Обработка настройки

def clean_headers(df):
  """Clean headers from unwanted characters"""
  df.columns = [re.sub(r'[\r\n\t]', '', col) for col in df.columns]
  return df


def get_dict_table(request, key, value, link=None):
  dict_initial = extract_initial_from_post(post=request.POST, prefix=f'dict-form-{key}', data={'key':'', 'value':''})
  extra = int('submit-btn' in request.POST and request.POST['submit-btn'] == key)
  if link:
    dict_initial = []
    for item in Dict.objects.filter(link=link):
      dict_initial.append({'key': item.key, 'value': item.value})

  if 'delete' in request.POST:
    raw_to_del = request.POST.get('delete', None)
    idx_del = re.findall(f'{key}-(\\d+)', raw_to_del)
    if not idx_del == []:
      dict_initial.pop(int(idx_del[0]))
  dict_form_set = forms.formset_factory(
    DictForm, 
    extra=extra)(
      initial=dict_initial, 
      prefix=f'dict-form-{key}')
  data = [{'key':dict_form_set.forms[i]['key'], 'value':dict_form_set.forms[i]['value'], 'btn': f'{key}-{i}'} for i in range(len(dict_form_set.forms))]
  if not dict_initial == [] or extra == 1:
    table = DictFormTable(data=data)
    RequestConfig(request).configure(table)
    table = table.as_html(request)
  else:
    table = None
  return render_to_string(
    'supplier/setting/dict_table.html',
    context={
      'key':key,
      'value':value,
      'manager': dict_form_set.management_form.as_div(),
      'initial':InitialForm(initial={'initial' : request.POST.get(f'initial-form-{key}-initial', link.initial if link else '')}, prefix=f'initial-form-{key}').as_p(),
      'table':table
    }
  )

def get_df(df: pd.DataFrame, links, initials, dicts, setting:Setting):
  for column, field in links.items():
    if field == 'article':
      df=df[df[column].notnull()]
    if field == 'name' and setting.differ_by_name:
      df=df[df[column].notnull()]
    if field in SP_PRICES and setting.priced_only:
      df = df[df[column].notnull()]
    buf = df[column].astype(str)
    buf = buf.replace(dicts[field], regex=True)
    buf.fillna(initials[field])
    df[column] = buf
  return df

def get_safe(value, type=None):
  if not type: return value
  if value == '': return value
  if type == int:
    return int(value)
  if type == float:
    return float(value)
  return value

def convert_sp(value, field):
  if field in SP_PRICES:
    num = float(value)
    return 0 if num < 0 else num
  if field in SP_INTEGERS:
    num = int(value)
    return 0 if num < 0 else num
  return value

def get_data(df: pd.DataFrame, request, setting: Setting):
  post = request.POST
  links = {
    link['value']: link['key'] for link in extract_initial_from_post(
    post, 
    prefix='link-form',
    data={'key':'', 'value':''},
    length=len(df.columns))
    if not link['key'] == ''
    }
  initials = {
    key: post.get(f'initial-form-{key}-initial', '')
    for key, value in LINKS.items() if not key == ''
  }

  for key, value in LINKS.items():
    if key == '': continue
    buf = value
    if key not in links.values():
      if initials[key] == '': continue
      while buf in df.columns:
        buf += ' Копия'
      links[buf] = key

      
  dicts = {}
  for column_name, field_name in links.items():
    if not column_name in df.columns:
      df[column_name] = None
    initials[field_name] = get_safe(initials[field_name], df[column_name].dtype)
    dicts[field_name] = {}
    for item in extract_initial_from_post(
                post, 
                prefix=f'dict-form-{field_name}', 
                data={'key':'', 'value':''}
                ):
      if not item['key'] in dicts[field_name]:
        dicts[field_name][get_safe(item['key'], df[column_name].dtype)] = get_safe(item['value'], df[column_name].dtype)
  return (get_df(df, links, initials, dicts, setting), links, initials, dicts)


class SettingCreate(SingleTableMixin, CreateView):
  '''Создание настроек <<supplier/<int:id>/setting/create/<int:f_id>/>>'''
  model = Setting
  form_class = SettingForm
  template_name = 'supplier/setting/create.html'
  prefix = 'setting-form'
  def get_success_url(self):
    return reverse('setting-upload', kwargs={'id':self.setting.pk, 'f_id': self.kwargs.get('f_id')})
  def get_table_class(self):
    return get_link_create_table()
  def get_table(self, **kwargs):
    return super().get_table(**kwargs, columns=list(self.df.columns), links=self.links)
  def get_table_data(self):
    return self.df.to_dict('records')
  def get_form(self):
    form = super().get_form(form_class = self.form_class)
    file_model = FileModel.objects.get(id=self.kwargs['f_id'])
    excel_file = pd.ExcelFile(file_model.file)
    choices = [(name, name) for name in excel_file.sheet_names]
    form.fields['sheet_name'].choices = choices
    form.fields['supplier'].initial=Supplier.objects.get(id=self.kwargs['id'])
    try:
      form.is_valid()
      sheet_name = form.cleaned_data['sheet_name']
    except:
      sheet_name = choices[0][0]
    self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')
    self.df = clean_headers(self.df)
    file_model.file.close()

    self.df, self.links, self.initials, self.dicts = get_data(self.df, self.request, form.instance)

    return form
  def form_valid(self, form):
    if not 'submit-btn' in self.request.POST or not self.request.POST['submit-btn'] == 'save':
      return self.form_invalid(form)
    self.setting = form.instance
    self.setting.save()
    for column_name, field_name in self.links.items():
      link = Link(setting=self.setting, key=field_name, value=column_name, initial=str(self.initials[field_name]) if not self.initials[field_name] == '' else None)
      link.save()
      for key, value in self.dicts[field_name].items():
        dict = Dict(link = link, key = str(key), value = str(value))
        dict.save()
    return super().form_valid(form)
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    self.dict_tables = []
    for key, value in LINKS.items():
      if key == '': continue
      self.dict_tables.append(get_dict_table(self.request, key, value))
    context['dict_tables'] = self.dict_tables
    return context

  
class SettingUpdate(SingleTableMixin, UpdateView):
  '''Обновление настройки <</setting/<int:id>/update/<int:f_id>/>>'''
  model = Setting
  form_class = SettingForm
  template_name = 'supplier/setting/create.html'
  prefix = 'setting-form'
  pk_url_kwarg = 'id'
  def get_success_url(self):
    return reverse('setting-upload', kwargs={'id':self.setting.pk, 'f_id': self.kwargs.get('f_id')})
  def get_table_class(self):
    return get_link_create_table()
  def get_table(self, **kwargs):
    return super().get_table(**kwargs, columns=list(self.df.columns), links=self.links)
  def get_table_data(self):
    return self.df.to_dict('records')
  def get_form(self):
    form = super().get_form(form_class = self.form_class)
    self.setting = form.instance
    file_model = FileModel.objects.get(id=self.kwargs['f_id'])
    excel_file = pd.ExcelFile(file_model.file)
    choices = [(name, name) for name in excel_file.sheet_names]
    form.fields['sheet_name'].choices = choices
    try:
      sheet_name = form.data['sheet_name']
    except:
      sheet_name = choices[0][0]
    self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')
    self.df = clean_headers(self.df)
    file_model.file.close()

    self.df, self.links, self.initials, self.dicts = get_data(self.df, self.request, self.setting)


    if self.links == {}:
      messages.info(self.request, 'Нажмите применить чтобы заработали замены')
      for link in Link.objects.filter(setting__pk=self.setting.pk):
        self.links[link.value] = link.key
        self.initials[link.key] = link.initial


    return form
  def form_valid(self, form):
    if not 'submit-btn' in self.request.POST or not self.request.POST['submit-btn'] == 'save':
      return self.form_invalid(form)
    self.setting = form.instance
    for link in Link.objects.filter(setting=self.setting):
      link.delete()
    for column_name, field_name in self.links.items():
      link = Link(setting=self.setting, key=field_name, value=column_name, initial=str(self.initials[field_name]) if not self.initials[field_name] == '' else None)
      link.save()
      for key, value in self.dicts[field_name].items():
        dict = Dict(link = link, key = str(key), value = str(value))
        dict.save()
    return super().form_valid(form)
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    self.dict_tables = []
    for key, value in LINKS.items():
      if key == '': continue
      self.dict_tables.append(
        get_dict_table(
          self.request, 
          key, 
          value, 
          Link.objects.filter(
            setting=self.setting, 
            key=key
          ).first() if self.dicts=={} else None
        )
      )
    context['dict_tables'] = self.dict_tables
    return context


class SettingDelete(DeleteView):
  model = Setting
  template_name = 'supplier/setting/confirm_delete.html'
  pk_url_kwarg='id'
  def get_success_url(self):
    return f'''/supplier/{self.get_object().supplier.pk}/settings'''

class SettingDetail(SingleTableView):
  '''Отображает настройку поставщика <<setting/<int:id>/>>'''
  model = Link
  table_class = LinkListTable
  template_name = 'supplier/setting/detail.html'
  def get_table_data(self):
    return Link.objects.filter(setting_id=self.kwargs['id'])
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['setting_id'] = self.kwargs['id']
    context['setting'] = Setting.objects.get(id=context['setting_id'])
    return context

class SettingUpload(View):
  def get(self, request, *args, **kwargs):
    return SettingDisplay.as_view()(request, *args, **kwargs)
  def post(self, request, *args, **kwargs):
    return upload_supplier_products(request, *args, **kwargs)

def get_upload_data(setting: Setting, df: pd.DataFrame):
  links = {link.value: link.key for link in Link.objects.filter(setting=setting)}
  rev_links = {value: key for key, value in links.items()}
  initials = {link.key: link.initial if link.initial else '' for link in Link.objects.filter(setting=setting)}
  dicts = {link.key: {item.key: item.value for item in Dict.objects.filter(link=link)} for link in Link.objects.filter(setting=setting)}
  df = get_df(df, links, initials, dicts, setting)
  if setting.differ_by_name:
    df.drop_duplicates(subset=[rev_links['name'], rev_links['article']], inplace=True)
  else:
    df.drop_duplicates(subset=[rev_links['article']], inplace=True)
  return df, links, initials, dicts

class SettingDisplay(DetailView):
  '''Проверка данных перед загрузкой <<setting/<int:id>/upload/<int:f_id>/>>'''
  model = Setting
  template_name='supplier/setting/upload.html'
  pk_url_kwarg = 'id'
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    setting = self.get_object()
    context['setting'] = setting
    context['supplier'] = setting.supplier
    file_model = FileModel.objects.get(id=self.kwargs['f_id'])
    try:
      excel_file = pd.ExcelFile(file_model.file)
      self.df = excel_file.parse(setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
      self.df = clean_headers(self.df)
      file_model.file.close()
      self.df, self.links, self.initials, self.dicts = get_upload_data(setting, self.df)
      table = get_upload_list_table()(links=self.links, data=self.df.to_dict('records'))
      RequestConfig(self.request, paginate=True).configure(table)
      context['table'] = table
    except BaseException as ex:
      messages.error(self.request, ex)
      file_model.file.delete()
      file_model.delete()
    return context
  def render_to_response(self, context, **response_kwargs):
    if not 'table' in context:
      return redirect('supplier')
    return super().render_to_response(context, **response_kwargs)

# Обработка файлов

class FileUpload(CreateView):
  '''
  Загрузка файла <<upload/<str:name>/<int:id>/>>
  name - url name to link after
  '''
  model = FileForm
  form_class = FileForm
  template_name = 'upload/upload.html'
  def form_valid(self, form):
    f_id = form.save().id
    id = self.kwargs.get('id', 0)
    if not id==0:
      self.success_url = reverse(self.kwargs['name'],
                                kwargs={'id' : id, 'f_id':f_id})
    else:
      self.success_url = reverse(self.kwargs['name'],
                                kwargs={'f_id':f_id})
    return super().form_valid(form)

# Обработка продуктов


def delete_supplier_product(request, **kwargs):
  '''
  Подвязка к функции удаления на странице поставщика
  <<supplier-product/<int:id>/delete/>>
  '''
  product = SupplierProduct.objects.get(id=kwargs['id'])
  id = product.supplier.id
  product.delete()
  return redirect('supplier-detail', id = id)


def upload_supplier_products(request, **kwargs):
  '''Тригер загрузки товаров <<setting/<int:id>/upload/<int:f_id>/upload/>>'''
  setting = Setting.objects.get(id=kwargs['id'])
  supplier = setting.supplier
  file_model = FileModel.objects.get(id=kwargs['f_id'])
  excel_file = pd.ExcelFile(file_model.file)
  df = excel_file.parse(setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
  df = clean_headers(df)
  file_model.file.close()
  df, links, initials, dicts = get_upload_data(setting, df)
  rev_links = {value: key for key, value in links.items()}

  discs = {}
  if 'discounts' in rev_links:
    discs = {disc: Discount.objects.get_or_create(supplier=supplier, name=disc)[0] for disc in df[rev_links['discounts']].unique()}
  discs['Есть РРЦ']= Discount.objects.get_or_create(supplier=supplier, name='Есть РРЦ')[0]
  discs['Нет РРЦ']= Discount.objects.get_or_create(supplier=supplier, name='Нет РРЦ')[0]
  cats = {}
  if 'category' in rev_links:
    cats = {cat: Category.objects.get_or_create(name=cat)[0] for cat in df[rev_links['category']].unique()}
  
  mans = {}
  if 'manufacturer' in rev_links:
    mans = {man: Manufacturer.objects.get_or_create(name=man)[0] for man in df[rev_links['manufacturer']].unique()}
  
  sp = []
  mp = []
  discs_add = []
  discs_remove = []
  new = 0
  overall = 0
  exs = []


  for _, row in df.iterrows():
    if setting.differ_by_name:
      products = [product for product in
                  SupplierProduct.objects.filter(supplier=supplier, article=row[rev_links['article']],
                                                 name=row[rev_links['name']])]
    else:
      products = [product for product in
                  SupplierProduct.objects.filter(supplier=supplier, article=row[rev_links['article']])]

    if products == []:
      if setting.differ_by_name:
        product, created = SupplierProduct.objects.get_or_create(supplier=supplier, article=row[rev_links['article']],
                                                                 name=row[rev_links['name']])
      else:
        product, created = SupplierProduct.objects.get_or_create(supplier=supplier, article=row[rev_links['article']])
      new += created
      products.append(product)

    for product in products:
      try:  
        for column, field in links.items():
          if field in SP_FKS:
            if field == 'category':
              setattr(product, field, cats[row[column]])
              continue
            if field == 'discounts':
              product.discounts.add(discs[row[column]])
              continue
            if field == 'manufacturer':
              setattr(product, field, mans[row[column]])
              continue
            continue
          if field in SP_PRICES:
            setattr(product, field, get_safe(row[column], float) * get_safe(setting.currency.value, float))
            continue
          setattr(product, field, convert_sp(row[column], field))
        if not product.rmp == 0 and not product.discounts.contains(discs['Есть РРЦ']):
          discs_add.append(
            product.discounts.through(supplierproduct=product,
                                      discount=discs['Есть РРЦ']))
          if product.discounts.contains(discs['Нет РРЦ']):
            discs_remove.append(product.discounts.through.objects.get(supplierproduct=product,
                                      discount=discs['Нет РРЦ']).id)
        elif product.rmp == 0 and not product.discounts.contains(discs['Нет РРЦ']):
          discs_add.append(
            product.discounts.through(supplierproduct=product,
                                      discount=discs['Нет РРЦ']))
          if product.discounts.contains(discs['Есть РРЦ']):
            discs_remove.append(product.discounts.through.objects.get(supplierproduct=product,
                                      discount=discs['Есть РРЦ']).id)
        if setting.update_main:
          main_product, _ = MainProduct.objects.get_or_create(supplier=supplier, article=product.article,
                                                              name=product.name)
          main_product.available = (product.stock > 0)
          main_product.search_vector = SearchVector('name', config='russian')
          main_product.manufacturer = product.manufacturer
          product.main_product = main_product
          mp.append(main_product)
        sp.append(product)
        overall += 1
      except BaseException as ex:
        exs.append(ex)

  MainProduct.objects.bulk_update(mp, fields=['supplier', 'article', 'name', 'search_vector', 'available', 'manufacturer'])
  SupplierProduct.objects.bulk_update(sp, fields=[field for field in links.values() if not field=='discounts'])
  SupplierProduct.objects.bulk_update(sp, fields=['supplier_price', 'rmp', 'main_product'])
  SupplierProduct.discounts.through.objects.bulk_create(discs_add)
  SupplierProduct.discounts.through.objects.filter(id__in=discs_remove).delete()
  for price in SP_PRICES:
    if price in rev_links:
      supplier.price_updated_at = timezone.now()
  if 'stock' in rev_links:
    supplier.stock_updated_at = timezone.now()
  supplier.save()
  messages.success(request, f'Добавлено товаров: {overall}, Новых: {new}')
  if not exs == []:
    ex_str = '''    '''.join([f'{ex}' for ex in exs[:min(len(exs), 5)]])
    messages.error(
      request,
      f'''Ошибок: {len(exs)}.     ''' + ex_str)
  return redirect('supplier-detail', id=supplier.pk)


class ManufacturerList(SingleTableView):
  '''Отображение производителей <<manufacturer/>>'''
  model = Manufacturer
  table_class = ManufacturerListTable
  template_name = 'manufacturer/list.html'

class ManufacturerDetail(SingleTableView):
  '''Отображение словоря производителя <<manufacturer/<int:id>/>>'''
  model = ManufacturerDict
  table_class = ManufacturerDictListTable
  template_name = 'manufacturer/dict.html'
  def get_table_data(self):
    return ManufacturerDict.objects.filter(manufacturer_id=self.kwargs['id'])
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['manufacturer_id'] = self.kwargs['id']
    context['manufacturer'] = Manufacturer.objects.get(id=context['manufacturer_id'])
    return context

class ManufacturerCreate(CreateView):
  '''Создание Производителя <<manufacturer/create/>>'''
  model = Manufacturer
  fields = '__all__'
  success_url = '/manufacturer/'
  template_name = 'manufacturer/create.html'

class ManufacturerDictCreate(CreateView):
  '''Обновление словаря Производителя <<manufacturer/<int:id>/add-alt/>>'''
  model = ManufacturerDict
  form_class = ManufacturerDictForm
  template_name = 'manufacturer/create.html'
  def get_form(self):
    form = super().get_form()
    form.fields['manufacturer'].initial = Manufacturer.objects.get(id=self.kwargs['id'])
    return form
  def get_success_url(self):
    return reverse('manufacturer-detail',kwargs={'id':self.kwargs['id']})

# Обработка валюты

class CurrencyList(SingleTableView):
  '''Отображает валюты <</currency/>>'''
  model = Currency
  table_class=CurrencyListTable
  template_name = 'currency/list.html'
  def get_table_data(self):
    return Currency.objects.exclude(name='KZT')

class CurrencyCreate(CreateView):
  model = Currency
  fields = '__all__'
  template_name = 'currency/create.html'
  def get_success_url(self):
    return '/currency/'

class CurrencyUpdate(UpdateView):
  model = Currency
  fields = '__all__'
  template_name = 'currency/update.html'
  pk_url_kwarg = 'id'
  def get_success_url(self):
    return '/currency/'
  
# Обработка категорий

class CategorySortSupplierProduct(FormView):
  '''Добавление товаров в категорию категорий <<category/>>'''
  model = Category
  template_name = 'category/sort.html'
  success_url = '/category/sort/'
  form_class = CategoryAddForm
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['search_form']=SortSupplierProductFilterForm(self.request.GET)
    queryset = SupplierProduct.objects.search_fields(self.request.GET)
    context['table'] = SortSupplierProductTable(queryset)
    RequestConfig(self.request).configure(context['table'])
    return context
  def form_valid(self, form):
    selected_products = self.request.POST.getlist('selected_items')
    category = form.cleaned_data['category']
    queryset = SupplierProduct.objects.search_fields(self.request.GET)
    if selected_products and category:
      queryset.filter(pk__in=selected_products).update(category=category)
    return super().form_valid(form)
  
class CategoryList(SingleTableView):
  '''Отображение категорий <<category/>>'''
  model = Category
  table_class = CategoryListTable
  template_name = 'category/list.html'

class CategoryCreate(CreateView):
  '''Создание Категории <<category/create/>>'''
  model = Category
  fields = '__all__'
  success_url = '/category/sort/'
  template_name = 'category/create.html'

class CategoryDelete(DeleteView):
  '''Удаление Категории <<category/<<int:id>>delete/>>'''
  model = Category
  pk_url_kwarg = 'id'
  success_url = '/category/'
  template_name = 'category/confirm_delete.html'

# Обработка наценок

class PriceManagerList(SingleTableView):
  '''Отображение наценок <</price_manager/>>'''
  model = PriceManager
  table_class = PriceManagerListTable
  template_name = 'price_manager/list.html'


def get_price_querry(price_from, price_to, price_prefix):
  if price_from and price_to:
    return Q(**{f'{price_prefix}__range':(price_from, price_to)})
  elif price_from:
    return Q(**{f'{price_prefix}__gte':price_from})
  elif price_to:
    return Q(**{f'{price_prefix}__lte':price_to})
  else:
    return Q()

class PriceManagerCreate(SingleTableMixin, CreateView):
  '''Создание Наценки <<price-manager/create/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  table_class = SupplierProductPriceManagerTable
  success_url = '/price-manager/'
  template_name = 'price_manager/create.html'
  def get_success_url(self):
    return f'/price-manager'
  def get_table_data(self):
    products = SupplierProduct.objects.all()
    if not hasattr(self, 'cleaned_data'):
      return products
    cleaned_data = self.cleaned_data
    products = products.filter(
      supplier=cleaned_data['supplier'])
    if cleaned_data['discounts']:
      products = products.filter(
        discounts__in=cleaned_data['discounts'])
    if cleaned_data['source'] in SP_PRICES:
      products = products.filter(get_price_querry(
        cleaned_data['price_from'],
        cleaned_data['price_to'],
        cleaned_data['source']))
    elif cleaned_data['source'] in MP_PRICES:
      products = products.filter(get_price_querry(
        cleaned_data['price_from'],
        cleaned_data['price_to'],
        f'''main_product__{cleaned_data['source']}'''))
    return products
  def get_form(self):
    form = super().get_form(self.form_class)
    discounts = Discount.objects.all()
    discounts = discounts.filter(supplier=form['supplier'].value())
    choices = [(None, 'Все группы скидок')]
    choices.extend([(disc.id, disc.name) for disc in discounts])
    form.fields['discounts'].choices = choices
    return form
  def form_valid(self, form):
    if not form.is_valid(): return self.form_invalid(form)
    cleaned_data = form.cleaned_data
    self.cleaned_data = cleaned_data
    if cleaned_data['dest'] == cleaned_data['source']:
      messages.error(self.request, f'Поле не может считатсься от себя же')
      return self.form_invalid(form)
    price_from = cleaned_data['price_from']
    price_to = cleaned_data['price_to']
    if price_from and price_to:
      if price_from>=price_to:
        messages.error(self.request, f'''Неверная ценовая зона: "От" больше или равен "До"''')
        return self.form_invalid(form)
    if price_to==0:
      messages.error(self.request, f'''Неверная ценовая зона: "До" равен 0''')
      return self.form_invalid(form)
    query = Q()
    if price_from and price_to:
      if price_from == 0:
        query |= Q(price_from__isnull=True)
      else:
        query |= (Q(price_from__gte=price_from)
                  &Q(price_from__lte=price_to))
      query |= (Q(price_to__gte=price_from)
                &Q(price_to__lte=price_to))
      query |= (Q(price_to__isnull=True)&Q(price_from__lte=price_to))
    elif price_to:
      query |= Q(price_from__lte=price_to)
      query |= Q(price_from__isnull=True)
    elif price_from:
      query |= Q(price_to__gte=price_from)
      query |= Q(price_to__isnull=True)
    conf_price_manager = PriceManager.objects.filter(query)
    if cleaned_data['discounts']:
      conf_price_manager = conf_price_manager.filter(
      Q(discounts__in=cleaned_data['discounts'])|
      Q(discounts__isnull=True))
    conf_price_manager = conf_price_manager.filter(
      dest=cleaned_data['dest'])
    conf_price_manager = conf_price_manager.filter(supplier=cleaned_data['supplier'])
    if conf_price_manager.exists():
      messages.error(self.request, f'Пересечение с другой наценкой: {conf_price_manager.first().name}')
      return self.form_invalid(form)
    if not self.request.POST.get('btn') == 'save': return self.form_invalid(form)
    form.save()
    messages.success(self.request, 'Наценка успешно добавлена')
    return super().form_invalid(form)

class PriceManagerDetail(DetailView):
  '''Детали Наценки <<price-manager/<int:id>/>>'''
  model = PriceManager
  template_name = 'price_manager/detail.html'
  pk_url_kwarg = 'id'
  context_object_name = 'price_manager'

class PriceManagerDelete(DeleteView):
  model = PriceManager
  template_name = 'price_manager/confirm_delete.html'
  pk_url_kwarg = 'id'
  success_url = '/price-manager/'

def apply_price_manager(price_manager: PriceManager):
  products = SupplierProduct.objects.all()
  products = products.filter(
    supplier=price_manager.supplier)
  if price_manager.discounts:
    products = products.filter(
      discounts__in=price_manager.discounts.all())
  if price_manager.source in SP_PRICES:
    products = products.filter(get_price_querry(
      price_manager.price_from,
      price_manager.price_to,
      price_manager.source))
  elif price_manager.source in MP_PRICES:
    products = products.filter(get_price_querry(
      price_manager.price_from,
      price_manager.price_to,
      f'''main_product__{price_manager.source}'''))

  mps = []
  for product in products:
    main_product = product.main_product
    main_product.price_managers.add(price_manager)
    setattr(main_product, 
            price_manager.dest, 
            math.ceil(getattr(
              product if price_manager.source in SP_PRICES else main_product, price_manager.source, None
              )*(1+price_manager.markup/100)+price_manager.increase))
    main_product.price_updated_at = timezone.now()
    mps.append(main_product)
  MainProduct.objects.bulk_update(mps, fields=[price_manager.dest, 'price_updated_at'])
  

# Обработка продуктов главного прайса

class MainProductUpdate(UpdateView):
    model = MainProduct
    form_class = MainProductForm
    template_name = 'main/product/update.html'
    success_url = '/'
    pk_url_kwarg = 'id'

def sync_main_products(request, **kwargs):
  """Обновляет только остатки (stock) в MainProduct из SupplierProduct"""
  updated = 0
  errors = 0

  supplier_products = SupplierProduct.objects.select_related("main_product").all()

  mps = []

  for sp in supplier_products:
    try:
      if not sp.main_product or sp.main_product.stock == sp.stock:
        continue  # пропускаем без связи

      mp = sp.main_product
      mp.stock = sp.stock
      mp.available = mp.stock > 0
      mp.stock_updated_at = timezone.now()
      mps.append(mp)

    except Exception as ex:
      errors += 1
      messages.error(request, f"Ошибка при обновлении {sp}: {ex}")
  updated = MainProduct.objects.bulk_update(mps, ['stock', 'stock_updated_at', 'available'])
  messages.success(request, f"Остатки обновлены у {updated} товаров, ошибок: {errors}")
  for price_manager in PriceManager.objects.all():
    apply_price_manager(price_manager)
  messages.success(request, 'Наценки применены')
  return redirect('main')


