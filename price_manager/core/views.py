# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404,
                              HttpResponse,
)
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
from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView
from decimal import Decimal, InvalidOperation

# Импорты моделей, функций, форм, таблиц
from .models import *
from .functions import *
from .forms import *
from .tables import *
from .filters import *

# Импорты сторонних библиотек
import pandas as pd
import json
import math


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
  
class SupplierDetail(SingleTableView):
  '''
  Таблица отображения товаров на странице поставщиков
  <<supplier/<int:id>/>>
  '''

  model = SupplierProduct
  table_class = SupplierProductListTable
  template_name = 'supplier/detail.html'
  def get_queryset(self):
    queryset = super().get_queryset().search_fields(self.request.GET).filter(
      supplier_id=self.kwargs['id'])
    return queryset
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['supplier_id'] = self.kwargs['id']
    context['supplier'] = Supplier.objects.get(id=context['supplier_id'])
    context['filter_form'] = SupplierFilterForm(self.request.GET or None)
    return context

class SupplierCreate(CreateView):
  '''Таблица создания Поставщиков <<supplier/create/>>'''
  model = Supplier
  fields = '__all__'
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

class SettingCreate(CreateView):
  '''Создание настроек <<supplier/<int:id>/setting/create/<int:f_id>/>>'''
  model = Setting
  form_class = SettingForm
  template_name = 'supplier/setting/create.html'
  def get_form(self, **kwargs):
    form = super().get_form(**kwargs)
    # Сетап листов и датафрейма
    self.file_model = FileModel.objects.get(id=self.kwargs['f_id'])
    excel_file = pd.ExcelFile(self.file_model.file)
    choices = [(name, name) for name in excel_file.sheet_names]
    # Установка начальных значений
    form.fields['sheet_name'].choices = choices
    form.fields['supplier'].initial=Supplier.objects.get(id=self.kwargs['id'])
    try:
      sheet_name = form.data['sheet_name']
    except:
      sheet_name = choices[0][0]
    self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')

    # Закрыть файл
    self.file_model.file.close()

    # Подготовка табличек для замены значений(с вводом для филлера пустых полей)
    initial = extract_initial_from_post(self.request.POST, 'widget_form',{'key':''}, len(self.df.columns))
    self.ins_initial = extract_initial_from_post(self.request.POST, 'initial_form', {'initial':''}, len(LINKS)-1)
    self.dict_formset = {}
    self.initial_formset = InitialsFormSet(initial=self.ins_initial, prefix='initial_form')
    InDictFormSet = forms.formset_factory(DictForm, extra=0)
    for key in LINKS.keys():
      if key == '': continue
      dict_initial = extract_initial_from_post(self.request.POST, f'dict_{key}_form', {'key':'', 'value':'', 'enable': True})
      if dict_initial == []:
        dict_initial = [{'key': '', 'value': None}]
      self.dict_formset[key] = InDictFormSet(initial=dict_initial, prefix=f'dict_{key}_form')

    self.mapping = {initial[i]['key'] : self.df.columns[i] 
                for i in range(len(self.df.columns))
                if not initial[i]['key'] == ''}
    
    for key, value in LINKS.items():
      if key == '': continue
      initial_value = self.ins_initial[list(LINKS.keys()).index(key)-1]['initial']
      if not key in self.mapping and not initial_value == '':
        buf = 0
        while f"{value}{' копия'*buf}" in self.df.columns: buf += 1
        self.df[f"{value}{' копия'*buf}"] = initial_value
        self.mapping[key] = f"{value}{' копия'*buf}"
        initial.append({'key':key})

    #  подготовка шторок на столбцы
    LinkFactory = forms.formset_factory(
                        form=LinksForm,
                        extra=len(self.df.columns))
    self.link_factory = LinkFactory(initial=initial, prefix='widget_form')


    return form

    
  def form_valid(self, form):
    unique = []
    for i in range(len(self.df.columns)):
      if f'form-{i}-key' in self.link_factory.data:
        buff = self.link_factory.data[f'form-{i}-key']
        if buff in unique and buff:
          form.add_error(None, 'Не уникальные поля')
          return self.form_invalid(form)
        unique.append(buff)
    if 'article' not in self.mapping:
      form.add_error(None, 'Не выбрано поле Артикул')
      return self.form_invalid(form)
    if 'name' not in self.mapping:
      form.add_error(None, 'Не выбрано поле Наименование')
      return self.form_invalid(form)
    # Очистка данных
    if 'priced_only' in form.data and form.data['priced_only']:
      failed_prices = []
      for price in PRICE_FIELDS:
        if not price in self.mapping:
          failed_prices.append(price)
          continue
        self.df = self.df[self.df[self.mapping[price]].notnull()]
      if len(failed_prices) == len(PRICE_FIELDS):
        form.add_error(None, 'Не выбрано поле цены')
        return self.form_invalid(form)
    self.df = self.df[self.df[self.mapping['article']].notnull()]
    self.df = self.df[self.df[self.mapping['name']].notnull()]

    # Логика замены значений
    for key in LINKS.keys():
      if key == '' or not key in self.mapping:
        continue
      value = self.mapping[key]

      # Изначальные значения
      indx = list(LINKS.keys()).index(key)-1
      if not self.ins_initial[indx]['initial'] == '':
        try:
          self.df.fillna({value: self.ins_initial[indx]['initial']}, inplace=True)
        except BaseException as ex:
          form.add_error(None, f'Что-то не так с начальными данными: {ex}')

      # Заменки
      action = self.request.POST.get(f'{key}_action')
      dict_initial = extract_initial_from_post(self.request.POST, f'dict_{key}_form', {'key':'', 'value':'', 'enable': True})
      if action == 'add':
        ExtraFormSet = forms.formset_factory(DictForm, extra=1, can_delete=True)
        self.dict_formset[key] = ExtraFormSet(initial=dict_initial, prefix=f'dict_{key}_form')
      try:
        col_dict = {item['key']:item['value'] for item in dict_initial if item['enable']}
        dtype = self.df[value].dtype
        self.df[value] = self.df[value].astype(str)
        self.df[value] = self.df[value].replace(col_dict, regex=True)
        self.df[value] = self.df[value].astype(dtype)
      except BaseException as ex:
        form.add_error(None, f'Что-то не так с заменами: {ex}')
    if not self.request.POST.get('submit-btn') == 'save':
      return super().form_invalid(form)
    setting = form.save()
    self.success_url = reverse('setting-upload', kwargs={'id':setting.id, 'f_id':self.file_model.id})
    for key, value in self.mapping.items():
      initial = self.ins_initial[list(LINKS.keys()).index(key)-1]['initial']
      link = Link.objects.create(
        setting = setting,
        initial = initial,
        key = key,
        value = value
      )
      dict_formset = DictFormSet(self.request.POST, prefix=f'dict_{key}_form')
      if dict_formset.is_valid():
        for i, cleaned in enumerate(dict_formset.cleaned_data):
          if not cleaned or not cleaned.get('enable'):
            continue
          Dict.objects.create(
              link=link,
              key=cleaned.get('key',''),
              value=cleaned.get('value','')
            )
    return super().form_valid(form)
  
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['link_factory'] = self.link_factory
    context['LINKS'] = LINKS
    # Таблички замен и формы для них
    context['dict_forms'] = self.dict_formset.items()
    context['initial_formset'] = self.initial_formset
    context['initial_forms'] = {
      list(LINKS.keys())[i]:self.initial_formset[i-1] for i in range(1, len(LINKS))
      }
    tables = {key:DictFormTable(value.forms) for key, value in self.dict_formset.items()}
    context['tables'] = tables
    widgets = [self.link_factory.forms[i]
                for i in range(len(self.df.columns))]
    context['table'] = get_link_create_table()(df=self.df, widgets=widgets, data=self.df.to_dict('records'))
    RequestConfig(self.request).configure(context['table'])
    return context
  
class SettingUpdate(UpdateView):
  '''Обновление настройки <</setting/<int:id>/update/<int:f_id>/>>'''
  model = Setting
  form_class = SettingForm
  template_name = 'supplier/setting/create.html'
  pk_url_kwarg='id'
  def get_form(self, **kwargs):
    form = super().get_form(**kwargs)
    # Сетап листов и датафрейма
    self.file_model = FileModel.objects.get(id=self.kwargs['f_id'])
    excel_file = pd.ExcelFile(self.file_model.file)
    choices = [(name, name) for name in excel_file.sheet_names]
    # Установка начальных значений
    form.fields['sheet_name'].choices = choices
    try:
      sheet_name = form.data['sheet_name']
    except:
      sheet_name = choices[0][0]
    self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')

    # Закрыть файл
    self.file_model.file.close()
    
    # Подготовка табличек для замены значений(с вводом для филлера пустых полей)
    initial = extract_initial_from_post(self.request.POST, 'widget_form',{'key':''}, len(self.df.columns))
    if not False in [item['key']=='' for item in initial]:
      links = Link.objects.filter(setting__id=self.kwargs.get('id', None)).values_list('key', 'value')
      for i in range(len(self.df.columns)):
        for link in links:
          if self.df.columns[i] == link[1]:
            initial[i]['key'] = link[0]
    self.ins_initial = extract_initial_from_post(self.request.POST, 'initial_form', {'initial':''}, len(LINKS)-1)
    if not False in [item['initial']=='' for item in self.ins_initial]:
      links = Link.objects.filter(setting__id=self.kwargs.get('id', None)).values_list('key', 'initial')
      for i in range(1, len(LINKS)):
        for link in links:
          if list(LINKS.keys())[i] == link[0]:
            if link[1]:
              self.ins_initial[i-1]['initial'] = link[1]
    self.dict_formset = {}
    self.initial_formset = InitialsFormSet(initial=self.ins_initial, prefix='initial_form')
    InDictFormSet = forms.formset_factory(DictForm, extra=0)
    for key in LINKS.keys():
      if key == '': continue
      link = Link.objects.filter(setting__id=self.kwargs.get('id', None), key=key).first()
      dict_initial = extract_initial_from_post(self.request.POST, f'dict_{key}_form', {'key':'', 'value':'', 'enable': True})
      if dict_initial == []:
        dicts = Dict.objects.filter(link=link).values_list('key', 'value')
        dict_initial=[{'key':item[0], 'value':item[1]} for item in dicts]
      elif dict_initial == []:
        dict_initial = [{'key': '', 'value': ''}]
      self.dict_formset[key] = InDictFormSet(initial=dict_initial, prefix=f'dict_{key}_form')

    self.mapping = {initial[i]['key'] : self.df.columns[i] 
                for i in range(len(self.df.columns))
                if not initial[i]['key'] == ''}
    
    for key, value in LINKS.items():
      if key == '': continue
      initial_value = self.ins_initial[list(LINKS.keys()).index(key)-1]['initial']
      if not key in self.mapping and not initial_value == '':
        buf = 0
        while f"{value}{' копия'*buf}" in self.df.columns: buf += 1
        self.df[f"{value}{' копия'*buf}"] = initial_value
        self.mapping[key] = f"{value}{' копия'*buf}"
        initial.append({'key':key})

    #  подготовка шторок на столбцы
    LinkFactory = forms.formset_factory(
                        form=LinksForm,
                        extra=len(self.df.columns))
    self.link_factory = LinkFactory(initial=initial, prefix='widget_form')


    
    return form

    
  def form_valid(self, form):
    unique = []
    for i in range(len(self.df.columns)):
      if f'form-{i}-key' in self.link_factory.data:
        buff = self.link_factory.data[f'form-{i}-key']
        if buff in unique and buff:
          form.add_error(None, 'Не уникальные поля')
          return self.form_invalid(form)
        unique.append(buff)
    if 'article' not in self.mapping:
      form.add_error(None, 'Не выбрано поле Артикул')
      return self.form_invalid(form)
    if 'name' not in self.mapping:
      form.add_error(None, 'Не выбрано поле Наименование')
      return self.form_invalid(form)
    # Очистка данных
    if 'priced_only' in form.data and form.data['priced_only']:
      failed_prices = []
      for price in PRICE_FIELDS:
        if not price in self.mapping:
          failed_prices.append(price)
          continue
        self.df = self.df[self.df[self.mapping[price]].notnull()]
      if len(failed_prices) == len(PRICE_FIELDS):
        form.add_error(None, 'Не выбрано поле цены')
        return self.form_invalid(form)
    self.df = self.df[self.df[self.mapping['article']].notnull()]
    self.df = self.df[self.df[self.mapping['name']].notnull()]

    # Логика замены значений
    for key in LINKS.keys():
      if key == '' or not key in self.mapping:
        continue
      value = self.mapping[key]

      # Изначальные значения
      indx = list(LINKS.keys()).index(key)-1
      if not self.ins_initial[indx]['initial'] == '':
        try:
          self.df.fillna({value: self.ins_initial[indx]['initial']}, inplace=True)
        except BaseException as ex:
          form.add_error(None, f'Что-то не так с начальными данными: {ex}')

      # Заменки
      action = self.request.POST.get(f'{key}_action')
      dict_initial = extract_initial_from_post(self.request.POST, f'dict_{key}_form', {'key':'', 'value':'', 'enable': True})
      if action == 'add':
        ExtraFormSet = forms.formset_factory(DictForm, extra=1, can_delete=True)
        self.dict_formset[key] = ExtraFormSet(initial=dict_initial, prefix=f'dict_{key}_form')
      try:
        col_dict = {item['key']:item['value'] for item in dict_initial if item['enable']}
        dtype = self.df[value].dtype
        self.df[value] = self.df[value].astype(str)
        self.df[value] = self.df[value].replace(col_dict, regex=True)
        self.df[value] = self.df[value].astype(dtype)
      except BaseException as ex:
        form.add_error(None, f'Что-то не так с заменами: {ex}')
    if not self.request.POST.get('submit-btn') == 'save':
      return super().form_invalid(form)
    setting = form.save()
    self.success_url = reverse('setting-upload', kwargs={'id':setting.id, 'f_id':self.file_model.id})
    Link.objects.filter(setting=setting).delete()
    for key, value in self.mapping.items():
      initial = self.ins_initial[list(LINKS.keys()).index(key)-1]['initial']
      link = Link.objects.create(
        setting = setting,
        initial = initial,
        key = key,
        value = value
      )
      dict_formset = DictFormSet(self.request.POST, prefix=f'dict_{key}_form')
      if dict_formset.is_valid():
        for i, cleaned in enumerate(dict_formset.cleaned_data):
          if not cleaned or not cleaned.get('enable'):
            continue
          Dict.objects.create(
              link=link,
              key=cleaned.get('key',''),
              value=cleaned.get('value','')
            )
    return super().form_valid(form)
  
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['link_factory'] = self.link_factory
    context['LINKS'] = LINKS
    # Таблички замен и формы для них
    context['dict_forms'] = self.dict_formset.items()
    context['initial_formset'] = self.initial_formset
    context['initial_forms'] = {
      list(LINKS.keys())[i]:self.initial_formset[i-1] for i in range(1, len(LINKS))
      }
    tables = {key:DictFormTable(value.forms) for key, value in self.dict_formset.items()}
    context['tables'] = tables
    widgets = [self.link_factory.forms[i]
                for i in range(len(self.df.columns))]
    context['table'] = get_link_create_table()(df=self.df, widgets=widgets, data=self.df.to_dict('records'))
    RequestConfig(self.request).configure(context['table'])
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
      mapping = {get_field_details(SupplierProduct)[link.key]['verbose_name']:link.value for link in Link.objects.filter(setting=setting)}
      links = {link.key: link.value for link in Link.objects.all().filter(setting=setting)}
      self.df = excel_file.parse(setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
      file_model.file.close()
      for link in Link.objects.all().filter(setting=setting):
        if link.value not in self.df.columns:
          self.df[link.value] = link.initial
      self.df = self.df[mapping.values()]
      if setting.priced_only:
        for price in PRICE_FIELDS:
          if not price in mapping:
            continue
          self.df = self.df[self.df[mapping[price]].notnull()]
      self.df = self.df[self.df[links['article']].notnull()]
      self.df = self.df[self.df[links['name']].notnull()]
      # Применение заменок
      for link in Link.objects.filter(setting_id=setting.id):
        col_dict = {entry.key: entry.value for entry in Dict.objects.filter(link=link)}
        try:
          self.df[link.value] = self.df[link.value].fillna(link.initial)
        except BaseException as ex:
          messages.error(None, f'Что-то не так с начальными данными: {ex}')
        try:
          dtype = self.df[link.value].dtype
          self.df[link.value] = self.df[link.value].astype(str)
          self.df[link.value] = self.df[link.value].replace(col_dict, regex=True)
          self.df[link.value] = self.df[link.value].astype(dtype)
        except BaseException as ex:
          messages.error(None, f'Что-то не так с заменами: {ex}')
      table = get_upload_list_table()(mapping=mapping, data=self.df.to_dict('records'))
      RequestConfig(self.request, paginate=True).configure(table)
      context['table'] = table
    except BaseException as ex:
      messages.error(self.request, ex)
      file_model.file.delete()
      file_model.delete()
    return context
  def render_to_response(self, context, **response_kwargs):
    try:
      if self.df.empty:
        return redirect('supplier')
    except:
      return redirect('supplier')
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

# !!!Временно: добавить класс удаления потом!!!
def delete_supplier_product(request, **kwargs):
  '''
  Подвязка к функции удаления на странице поставщика
  <<supplier-product/<int:id>/delete/>>
  '''
  product = SupplierProduct.objects.get(id=kwargs['id'])
  id = product.supplier.id
  product.delete()
  return redirect('supplier-detail', id = id)

# !!!Временно: не загружать через ссылку!!!
def upload_supplier_products(request, **kwargs):
  '''Тригер загрузки товаров <<setting/<int:id>/upload/<int:f_id>/upload/>>'''
  setting = Setting.objects.get(id=kwargs['id'])
  supplier = setting.supplier
  file_model = FileModel.objects.get(id=kwargs['f_id'])
  excel_file = pd.ExcelFile(file_model.file)
  links = {link.key: link.value for link in Link.objects.all().filter(setting_id=setting.id)}

  df = excel_file.parse(setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
  df = df.drop_duplicates(subset=[links['name'], links['article']])
  file_model.file.close()

  # Фильтры
  if setting.priced_only:
    for price in PRICE_FIELDS:
      if price in links:
        df = df[df[links[price]].notnull()]
  df = df[df[links['article']].notnull()]
  df = df[df[links['name']].notnull()]

  # Замены по словарям
  for link in Link.objects.filter(setting_id=setting.id):
    col_dict = {entry.key: entry.value for entry in Dict.objects.filter(link=link)}
    df[link.value] = df[link.value].fillna(link.initial)
    col_type = df[link.value].dtype
    df[link.value] = df[link.value].astype(str)
    df[link.value] = df[link.value].replace(col_dict, regex=True)
    df[link.value] = df[link.value].astype(col_type)

  manufacturers = {}
  categories = {}
  discounts = {}
  products = []
  m_products = []
  sp_fields = ['supplier']
  sp_fields.extend(list(LINKS.keys())[1:])
  if setting.id_as_sku:
    sp_fields.append('main_product')
  mp_fields = ['sku', 'supplier', 'article', 'name', 'category', 'stock',
               'manufacturer', 'updated_at']

  # Справочники
  if 'manufacturer' in links:
    for manu_name in df[links['manufacturer']].unique():
      manufacturer, _ = Manufacturer.objects.get_or_create(name=manu_name)
      manufacturers[manu_name] = manufacturer
  if 'category' in links:
    for cate_name in df[links['category']].unique():
      category, _ = Category.objects.get_or_create(name=cate_name)
      categories[cate_name] = category
  if 'discount' in links:
    for discount_name in df[links['discount']].unique():
      discount, _ = Discount.objects.get_or_create(name=discount_name)
      discounts[discount_name] = discount

  # Основной цикл
  for _, row in df.iterrows():
    data = {}
    m_data = {}
    data['supplier'] = supplier
    data['currency'] = setting.currency
    if 'category' in links:
      data['category'] = categories.get(row[links['category']]) if 'category' in links else None
    if 'manufacturer' in links:
      data['manufacturer'] = manufacturers.get(row[links['manufacturer']]) if 'manufacturer' in links else None
    if 'discount' in links:
      data['discount'] = discounts.get(row[links['discount']]) if 'discount' in links else None

    def get_decimal(val):
      try:
        return Decimal(val)
      except:
        return Decimal()
    def get_int(val):
      try:
        return int(val)
      except:
        return 0

    for key in sp_fields:
      if key in data:
        continue
      if key == 'rmp_kzt' and 'rmp_raw' in data and not 'rmp_kzt' in links:
        raw_rmp = get_decimal(data['rmp_raw'])
        data['rmp_kzt'] = raw_rmp * setting.currency.value
        continue
      if key == 'supplier_price_kzt' and 'supplier_price' in data and not 'supplier_price_kzt' in links:
        sup_price = get_decimal(data['supplier_price'])
        data['supplier_price_kzt'] = sup_price * setting.currency.value
        continue
      if key in links:
        val = row[links[key]]
        if key in ['supplier_price', 'rmp_raw', 'rmp_kzt', 'supplier_price_kzt']:
          data[key] = get_decimal(val)
        elif key in ['stock']:
          stock = get_int(val)
          if stock < 0: continue
          data[key] = stock
        else:
          data[key] = val

    for key in mp_fields:
      if key in data:
        m_data[key] = data[key]
    m_data['sku'] = f'''{data['supplier'].pk}-{data['article']}'''

    if setting.id_as_sku:
      m_products.append(MainProduct(**m_data))
      products.append(SupplierProduct(main_product=m_products[-1], **data))
    else:
      products.append(SupplierProduct(**data))

  mp = MainProduct.objects.bulk_create(
    m_products,
    update_conflicts=True,
    unique_fields=NECESSARY,
    update_fields=[field for field in mp_fields if not field in NECESSARY]
  )
  sp = SupplierProduct.objects.bulk_create(
    products,
    update_conflicts=True,
    unique_fields=NECESSARY,
    update_fields=[field for field in sp_fields if not field in NECESSARY]
  )

  MainProduct.objects.update(search_vector=SearchVector('name', config='russian'))
  messages.success(
    request,
    f'Обработано {len(sp)}. Добавлено в главный прайс {len(mp)}'
  )
  file_model.file.delete()
  file_model.delete()
  setting.id_as_sku = False
  setting.save()
  return redirect('supplier-detail', id=supplier.id)
# Обработка производителей

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
  '''Отображение наценок <<price_manager/>>'''
  model = PriceManager
  table_class = PriceManagerListTable
  template_name = 'price_manager/list.html'

class PriceManagerCreate(CreateView):
  '''Создание Наценки <<price-manager/create/>>'''
  model = PriceManager
  fields = '__all__'
  success_url = '/price-manager/'
  template_name = 'price_manager/create.html'
  def form_valid(self, form):
    if form.is_valid():
      cleaned_data = form.cleaned_data
      if cleaned_data['dest'] == cleaned_data['source']:
        messages.error(self.request, f'Поле не может считатсься от себя же')
        return self.form_invalid(form)
      price_manager = PriceManager.objects.filter(
        supplier=cleaned_data['supplier'],
        discount=cleaned_data['discount'],
        dest=cleaned_data['dest'],
        price_from__range=(cleaned_data['price_from'], cleaned_data['price_to']),
        price_to__range=(cleaned_data['price_from'], cleaned_data['price_to']),
      ).last()
      if price_manager:
        messages.error(self.request, f'Пересечение с другой наценкой: {price_manager.name}')
        return self.form_invalid(form)
    return super().form_valid(form)

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

def price_manager_apply_all(request, **kwargs):
  for price_manager in PriceManager.objects.all():
    if price_manager.source in ['rmp_kzt', 'supplier_price']:
      supplier_products = SupplierProduct.objects.filter(
        Q(**{f'{price_manager.source}__gte': price_manager.price_from})|
        Q(**{f'{price_manager.source}__lte': price_manager.price_to})
      )
      products = MainProduct.objects.filter(pk__in=supplier_products.values_list('main_product', flat=True))
    else:
      products = MainProduct.objects.filter(
        Q(**{f'{price_manager.source}__gte': price_manager.price_from})|
        Q(**{f'{price_manager.source}__lte': price_manager.price_to}))
    if price_manager.supplier:
      products.filter(supplier=price_manager.supplier)
    if price_manager.discount:
      products.filter(category=price_manager.discount)
    for product in products:
      product.price_manager = price_manager
      if price_manager.source in ['rmp_kzt', 'supplier_price']:
        price_source = getattr(
          SupplierProduct.objects.filter(main_product=product).first(),
          price_manager.source)
      else:
        price_source = getattr(product,
          price_manager.source)
      setattr(product, price_manager.dest, math.ceil(price_source*(1+price_manager.markup/100)+price_manager.increase))
    MainProduct.objects.bulk_update(products, fields=[price_manager.dest, 'price_manager', 'updated_at'])
  messages.success(request, 'Наценки применены')
  return redirect('main')

def price_manager_apply(request, **kwargs):
  id = kwargs.pop('id')
  if not id:
    messages.error(request, 'Нет такой наценки')
    return redirect('price-manager')
  price_manager = PriceManager.objects.get(id=id)
  if price_manager.source in ['rmp_kzt', 'supplier_price_kzt']:
    supplier_products = SupplierProduct.objects.all()
    if price_manager.price_from:
      supplier_products = supplier_products.filter(
        Q(**{f'{price_manager.source}__gte': price_manager.price_from}))
    if price_manager.price_to:
      supplier_products = supplier_products.filter(
        Q(**{f'{price_manager.source}__lte': price_manager.price_to}))
    products = MainProduct.objects.filter(pk__in=supplier_products.values_list('main_product', flat=True))
  else:
    products = MainProduct.objects.all()
    if price_manager.price_from:
      products = products.filter(
        Q(**{f'{price_manager.source}__gte': price_manager.price_from}))
    if price_manager.price_to:
      products = products.filter(
        Q(**{f'{price_manager.source}__lte': price_manager.price_to}))
  if price_manager.supplier:
    products = products.filter(supplier=price_manager.supplier)
  if price_manager.discount:
    products = products.filter(discount=price_manager.discount)
  for product in products:
    product.price_manager = price_manager
    if price_manager.source in ['rmp_kzt', 'supplier_price_kzt']:
      price_source = getattr(
        SupplierProduct.objects.filter(main_product=product).first(),
        price_manager.source)
    else:
      price_source = getattr(product,
        price_manager.source)
    setattr(product, price_manager.dest, math.ceil(price_source*(1+price_manager.markup/100)+price_manager.increase))
  MainProduct.objects.bulk_update(products, fields=[price_manager.dest, 'price_manager', 'updated_at'])
  return redirect('price-manager')

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

  for sp in supplier_products:
      try:
          if not sp.main_product:
              continue  # пропускаем без связи

          mp = sp.main_product
          mp.stock = sp.stock

      except Exception as ex:
          errors += 1
          messages.error(request, f"Ошибка при обновлении {sp}: {ex}")
  updated = SupplierProduct.objects.bulk_update(supplier_products, ['stock', 'updated_at'])

  messages.success(request, f"Остатки обновлены у {updated} товаров, ошибок: {errors}")
  return price_manager_apply_all(request, **kwargs)

