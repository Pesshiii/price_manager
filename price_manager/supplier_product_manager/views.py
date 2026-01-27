# Импорты из django
from django.contrib import messages
from django.contrib.postgres.search import SearchVector
from django.conf import settings
from django.db.models import ExpressionWrapper, Q, BooleanField, Value
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404)
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse
from django.views.generic import (View, TemplateView,
                                  DetailView,
                                  CreateView,
                                  UpdateView,
                                  DeleteView)
from django.core.paginator import Paginator
from django.core.files.base import ContentFile
 


from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh, retarget
from django.template.context_processors import csrf
from crispy_forms.utils import render_crispy_form

# Импорты моделей, функций, форм, таблиц
from file_manager.models import FileModel
from main_product_manager.models import MainProduct, MainProductLog, MP_PRICES
from product_price_manager.models import PriceManager
from core.functions import extract_initial_from_post
from .models import DictItem
from .forms import *
from .tables import *
from .filters import *
from .tasks import upload_supplier_files

import io, os
from typing import Dict, Any
import pandas as pd
import numpy as np
from decimal import Decimal, InvalidOperation
import re

class SupplierDetail(SingleTableMixin, FilterView):
  '''
  Таблица отображения товаров на странице поставщиков
  <<supplier/<int:id>/>>
  '''

  model = SupplierProduct
  table_class = SupplierProductListTable
  filterset_class = SupplierProductFilter
  template_name = 'supplier/detail.html'
  def get(self, request, *args, **kwargs):
    self.supplier = Supplier.objects.get(pk=self.kwargs.get('pk', None))
    # for setting in self.supplier.settings.all():
    #   setting.delete()
    return super().get(request, *args, **kwargs)
  def get_table_data(self):
    return super().get_table_data().filter(supplier=self.supplier)
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['supplier'] = self.supplier
    pms = PriceManager.objects.filter(supplier=self.supplier).annotate(
    is_published=ExpressionWrapper(
      Q(fixed_price__isnull=False)|~Q(fixed_price=0),
      output_field=BooleanField()
    )
)
    context['pricemanagers'] = pms
    return context


# Обработка настройки
class UploadSupplierFile(CreateView):
  model = SupplierFile
  form_class = UploadFileForm
  template_name = 'supplier_product/partials/uppload_file_partial.html'
  success_url = '/supplier'
  valid=False
  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['pk'] = self.kwargs.get('pk')
    return kwargs
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context["supplier"] = Supplier.objects.get(pk=self.kwargs.get('pk'))
    return context
  def form_valid(self, form):
    instance = form.save(commit=False)
    sfs = []
    if not instance.setting:
      number = 0
      created = False
      while not created:
        try:
          anti_copy = f'({number})' if not number == 0 else ''
          setting = Setting.objects.create(name = os.path.splitext(os.path.basename(instance.file.path))[0] + anti_copy, supplier = Supplier.objects.get(pk=self.kwargs.get('pk')))
          created = True
        except:
          number += 1
          created = False
    else:
      setting = instance.setting
    for supplier_file in setting.supplier_files.all():
      supplier_file.file.delete()
      supplier_file.delete()
    if not os.path.splitext(instance.file.name)[1] == '.csv':
      print('1:', timezone.now())
      excel_document = pd.ExcelFile(instance.file, engine='calamine')
      print('2:', timezone.now())
      for sheet_name in excel_document.sheet_names:
        print('3:', timezone.now())
        df = excel_document.parse(sheet_name, engine='calamine').dropna(axis=0, how='all').dropna(axis=1,how='all')
        csv_buffer = io.StringIO()
        print('4:', timezone.now())
        df.to_csv(csv_buffer, index=False, encoding='utf-8')
        csv_content = csv_buffer.getvalue()
        csv_file = ContentFile(csv_content.encode('utf-8'))
        sf = SupplierFile.objects.create(setting=setting)
        print('5:', timezone.now())
        sf.file.save(sheet_name + '.csv', csv_file)
        print('6:', timezone.now())
        sfs.append(sf)
      setting.sheet_name = os.path.splitext(sfs[0].file.name)[0]
      setting.save()
    if not instance.setting:
      redirect_url = reverse('supplier-detail', kwargs={'pk':setting.supplier.pk}) + '#setting'
      return HttpResponseClientRedirect(redirect_url)
    messages.info(self.request, f"Загрузка файла через настройку {setting.name}")
    messages.info(self.request, f"загружено {len(load_setting(setting.pk))} файлов")
    self.valid = True
    return super().form_valid(form)
  def render_to_response(self, context, **response_kwargs):
    response = super().render_to_response(context, **response_kwargs)
    if self.valid:
      return HttpResponseClientRefresh
    return response
  def get_success_url(self):
    return reverse('supplier-upload', kwargs={'pk':self.kwargs.get('pk')})
  
class XMLTableView(TemplateView):
  template_name = 'supplier_product/partials/csv_table.html'
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      context = super().get_context_data(**kwargs)
      df = get_df(self.kwargs.get('pk')).fillna('')
      page = int(self.request.GET.get('page', 1))
      items = Paginator(df.to_records(index=False), per_page=5).page(page)
      context['pk'] = self.kwargs.get('pk')
      context['items'] = items
      context['columns'] = df.columns
      context["page"] = page
      return context
  
class SettingUpdate(UpdateView):
  model = Setting
  form_class = SettingForm
  template_name = "supplier_product/setting_update.html"
  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['pk'] = self.kwargs.get('pk')
    return kwargs
  def get_form(self):
    form = super().get_form(self.form_class)
    form.fields['sheet_name'].choices = [(os.path.splitext(os.path.basename(sf.file.path))[0] , os.path.splitext(os.path.basename(sf.file.path))[0]) for sf in SupplierFile.objects.filter(setting=self.kwargs.get('pk'))]
    return form
  def get_success_url(self):
    return reverse('setting-update', kwargs={'pk': self.kwargs.get('pk')})
  def form_valid(self, form):
    pk = self.kwargs.get('pk')
    setting = Setting.objects.get(pk=pk)
    post = self.request.POST
    df = get_df(pk)
    
    if post.get('action', None) == 'delete':
      for mfile in setting.supplier_files.all():
        mfile.file.delete()
        mfile.delete()
      setting.delete()
      return HttpResponseClientRefresh()

    if not setting.name == form.cleaned_data['name']:
      os.makedirs(settings.MEDIA_ROOT / f'''setting_{form.cleaned_data['name']}''', exist_ok=True)
      for mfile in setting.supplier_files.all():
        rel_path = f'''setting_{form.cleaned_data['name']}\\{os.path.basename(mfile.file.path)}'''
        full_path = settings.MEDIA_ROOT / rel_path
        os.rename(mfile.file.path, full_path)
        mfile.file.name = rel_path
        mfile.save()
      setting.name = form.cleaned_data['name']
      setting.save()
    if not setting.sheet_name == form.cleaned_data['sheet_name']:
      setting.sheet_name = form.cleaned_data['sheet_name']
      setting.save()
    
    link_formset = get_linkformset(post, pk)
    indicts = get_indicts(post, pk)

    if not link_formset.is_valid(): return self.form_invalid(form)

    for i in range(len(link_formset.cleaned_data)):
      link = None

      if not link_formset.cleaned_data[i]['key']: continue
      link = Link.objects.get(setting=pk, key=link_formset.cleaned_data[i]['key'])

      if indicts[link_formset.cleaned_data[i]['key']]['initial'].is_valid():
        link.initial = indicts[link_formset.cleaned_data[i]['key']]['initial'].cleaned_data['initial']
      link.value = df.columns[i]
      link.save()
    for link, value in LINKS.items():
      if link == '': continue
      if indicts[link]['dict_formset'].is_valid():
        mlink = Link.objects.get(setting=pk, key=link)
        DictItem.objects.filter(link=mlink).delete()
        for item in indicts[link]['dict_formset'].cleaned_data:
          if item['key'] == '': continue
          DictItem.objects.get_or_create(link=mlink, key=item['key'], value=item['value'])
    if post.get('action') and post.get('action') == 'upload':
      products = load_setting(pk)
      messages.info(self.request, f'Обработано {len(products[0])} товаров. Добавлено {len(products[1])} товаров главного прайса')
    return self.form_invalid(form)
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    pk = self.kwargs.get('pk')
    post = self.request.POST
    context['links'] = get_indicts(post, pk)
    context["link_formset"] = get_linkformset(post, pk)
    return context
  

def load_setting(pk):
  setting = Setting.objects.get(pk=pk)
  links = Link.objects.filter(setting=setting)
  df = get_df(pk)
  for link in links:
    if link.value == '': continue
    df[link.value] = df[link.value].fillna(link.initial)
    for dict in link.dicts.all():
      df[link.value] = df[link.value].replace(dict.key, dict.value)
    df = df.rename(columns={link.value : link.key})
  if not 'article' in df.columns: return None
  df = df.replace('', np.nan)
  df = df.loc[:,[link.key for link in links if not link.key=='' and link.key in df.columns]].convert_dtypes()
  df = df.dropna(subset=['article'])
  for link in links:
    if link.key in df.columns and link.key in SP_NUMBERS:
      df[link.key] = pd.to_numeric(df[link.key], errors='coerce')
  df = df.dropna(subset=[link.key for link in links if not link.key=='article' and not link.key == 'name' and link.key in df.columns], how='all')
  if 'manufacturer' in df.columns:
    df['manufacturer'] = df['manufacturer'].apply(lambda s: Manufacturer.objects.get_or_create(name=s)[0] if s else None)
  if 'discount' in df.columns:
    df['discount'] = df['discount'].apply(lambda s: Discount.objects.get_or_create(supplier=setting.supplier, name=s)[0] if s else None)
  df = df.replace({pd.NA: None, float('nan'): None})
  if 'name' in df.columns:
    df = df.dropna(subset=['name'])
    sp_model_instances = map(
      lambda row: SupplierProduct(
        supplier=setting.supplier,
        article=row.article,
        name=row.name,
        **{
          link.key: Decimal(str(getattr(row, link.key))) if link.key in SP_NUMBERS else getattr(row, link.key)
          for link in links 
          if not link.key=='article' and not link.key == 'name' and link.key in df.columns
          and getattr(row, link.key)
        }
      ), df.itertuples(index=False))
    sp_update_fields = [link.key for link in links if not link.key=='article' and not link.key == 'name' and link.key in df.columns]
    sp_update_fields.append('updated_at')
    sps = SupplierProduct.objects.bulk_create(
      sp_model_instances, 
      update_conflicts=True, 
      update_fields=sp_update_fields,
      unique_fields=['supplier', 'article', 'name'])
    mp_model_instances = map(
      lambda row: MainProduct(
        supplier=setting.supplier,
        article=row.article,
        **{'manufacturer': df['manufacturer'] if 'manufacturer' in df.columns else None}
      ) if not MainProduct.objects.filter(supplier=setting.supplier, article=row.article).exists() else None, df.itertuples(index=False))
    mps = MainProduct.objects.bulk_create(
      [_ for _ in mp_model_instances if _],
      # При дальнейшей работе следует убрать: непредсказуемые результаты
      ignore_conflicts=True,

      unique_fields=['supplier', 'article']
    )
    return (sps, mps)
    
    


class SettingList(SingleTableView):
  '''Отображение наценок << /supplier/<int:pk>/settings >>'''
  model = Setting
  table_class = SettingListTable
  template_name = 'supplier/partials/setting_table.html'
  def get(self, request, *args, **kwargs):
    if self.request.htmx:
      self.template_name = 'supplier/partials/setting_table.html#table'
    return super().get(request, *args, **kwargs)
  def get_queryset(self):
    qs = super().get_queryset()
    pk = self.kwargs.get('pk', None)
    if pk:
      return qs.filter(supplier=pk)
    return qs
  
# def clean_headers(df):
#   """Clean headers from unwanted characters"""
#   df.columns = [re.sub(r'[\r\n\t]', '', str(col)) for col in df.columns]
#   return df


# def get_dict_table(request, key, value, link=None):
#   dict_initial = extract_initial_from_post(post=request.POST, prefix=f'dict-form-{key}', data={'key':'', 'value':''})
#   extra = int('submit-btn' in request.POST and request.POST['submit-btn'] == key)
#   if link:
#     dict_initial = []
#     for item in Dict.objects.filter(link=link):
#       dict_initial.append({'key': item.key, 'value': item.value})

#   if 'delete' in request.POST:
#     raw_to_del = request.POST.get('delete', None)
#     idx_del = re.findall(f'{key}-(\\d+)', raw_to_del)
#     if not idx_del == []:
#       dict_initial.pop(int(idx_del[0]))
#   dict_form_set = forms.formset_factory(
#     DictForm, 
#     extra=extra)(
#       initial=dict_initial, 
#       prefix=f'dict-form-{key}')
#   data = [{'key':dict_form_set.forms[i]['key'], 'value':dict_form_set.forms[i]['value'], 'btn': f'{key}-{i}'} for i in range(len(dict_form_set.forms))]
#   if not dict_initial == [] or extra == 1:
#     table = DictFormTable(data=data)
#     RequestConfig(request).configure(table)
#     table = table.as_html(request)
#   else:
#     table = None
#   return render_to_string(
#     'supplier/setting/dict_table.html',
#     context={
#       'key':key,
#       'value':value,
#       'manager': dict_form_set.management_form.as_div(),
#       'initial':InitialForm(initial={'initial' : request.POST.get(f'initial-form-{key}-initial', link.initial if link else '')}, prefix=f'initial-form-{key}').as_p(),
#       'table':table
#     }
#   )

# def get_df(df: pd.DataFrame, links, initials, dicts, setting:Setting):
#   for column, field in links.items():
#     if not column in df.columns:
#       df[column] = None
#     if field == 'article':
#       df=df[df[column].notnull()]
#     if field == 'name' and setting.differ_by_name:
#       df=df[df[column].notnull()]
#     if field in SP_PRICES and setting.priced_only:
#       df = df[df[column].notnull()]
#     buf: pd.Series = df[column]
#     buf = buf.fillna(initials[field])
#     buf = buf.astype(str)
#     buf = buf.replace(dicts[field], regex=True)
#     df[column] = buf
#   return df

# def get_safe(value, type=None):
#   if not type: return value
#   if value == '': return value
#   if type == int:
#     return int(value)
#   if type == float:
#     return float(value)
#   return value

# def get_safe(value, type=None):
#     """
#     Универсальное приведение типов.
#     Не меняет файл поставщика, только приводит значение в момент чтения.
#     Поддерживает форматы: '950,00', '950.00', '1 234,56', '950.'
#     """
#     if not type or value in ('', None):
#         return value

#     # если уже число – просто вернём
#     if isinstance(value, (int, float, Decimal)):
#         v = value
#     else:
#         # строку нормализуем только в памяти
#         v = str(value).strip()
#         # убираем пробелы и неразрывные пробелы
#         v = v.replace(' ', '').replace('\xa0', '')
#         # если есть запятая и нет точки – считаем, что это десятичный разделитель
#         if ',' in v and '.' not in v:
#             v = v.replace(',', '.')

#     try:
#         if type == int:
#             return int(float(v))
#         if type == float:
#             return float(v)
#         if type == Decimal:
#             return Decimal(str(v))
#     except (ValueError, InvalidOperation):
#         # если совсем не получилось – оставим как есть
#         return 0


# def convert_sp(value, field):
#   if field in SP_PRICES:
#     if not value or  value == '':
#       num = 0
#     else:
#       num = get_safe(value, Decimal)
#     return 0 if num < 0 else num
#   if field in SP_INTEGERS:
#     if not value or  value == '':
#       num = 0
#     else:
#       num = get_safe(value, int)
#     return 0 if num < 0 else num
#   return value


# def convert_sp(value, field):
#     """
#     Приведение значений для SupplierProduct.
#     Цены и остатки — через get_safe, без правок исходного файла.
#     """
#     # цены (supplier_price, rrp)
#     if field in SP_PRICES:
#         num = get_safe(value, Decimal)
#         if num in ('', None):
#             num = Decimal('0')
#         if num < 0:
#             num = Decimal('0')
#         return num

#     # целые поля (stock)
#     if field in SP_INTEGERS:
#         num = get_safe(value, int)
#         if num in ('', None):
#             num = 0
#         if num < 0:
#             num = 0
#         return num

#     # остальные поля оставляем как есть
#     return value

# def get_data(df: pd.DataFrame, request, setting: Setting):
#   post = request.POST
#   links = {
#     link['value']: link['key'] for link in extract_initial_from_post(
#     post, 
#     prefix='link-form',
#     data={'key':'', 'value':''},
#     length=len(df.columns))
#     if not link['key'] == ''
#     }
#   initials = {
#     key: post.get(f'initial-form-{key}-initial', '')
#     for key, value in LINKS.items() if not key == ''
#   }

#   for key, value in LINKS.items():
#     if key == '': continue
#     buf = value
#     if key not in links.values():
#       if not key in initials or initials[key] == '': continue
#       while buf in df.columns:
#         buf += ' Копия'
#       links[buf] = key

      
#   dicts = {}
#   for column_name, field_name in links.items():
#     if not column_name in df.columns:
#       df[column_name] = None
#     initials[field_name] = initials[field_name]
#     dicts[field_name] = {}
#     for item in extract_initial_from_post(
#                 post, 
#                 prefix=f'dict-form-{field_name}', 
#                 data={'key':'', 'value':''}
#                 ):
#       if not item['key'] in dicts[field_name]:
#         dicts[field_name][item['key']] = item['value']
#   return (get_df(df, links, initials, dicts, setting), links, initials, dicts)


# class SettingCreate(SingleTableMixin, CreateView):
#   '''Создание настроек <<supplier/<int:id>/setting/create/<int:f_id>/>>'''
#   model = Setting
#   form_class = SettingForm
#   template_name = 'supplier/setting/create.html'
#   prefix = 'setting-form'
#   def get_success_url(self):
#     return reverse('setting-upload', kwargs={'id':self.setting.pk, 'f_id': self.kwargs.get('f_id')})
#   def get_table_class(self):
#     return get_link_create_table()
#   def get_table(self, **kwargs):
#     return super().get_table(**kwargs, columns=list(self.df.columns), links=self.links)
#   def get_table_data(self):
#     return self.df.to_dict('records')
#   def get_form(self):
#     form = super().get_form(form_class = self.form_class)
#     file_model = FileModel.objects.get(id=self.kwargs['f_id'])
#     excel_file = pd.ExcelFile(file_model.file)
#     choices = [(name, name) for name in excel_file.sheet_names]
#     form.fields['sheet_name'].choices = choices
#     form.fields['supplier'].initial=Supplier.objects.get(id=self.kwargs['id'])
#     try:
#       form.is_valid()
#       sheet_name = form.cleaned_data['sheet_name']
#     except:
#       sheet_name = choices[0][0]
#     try:
#       self.df = excel_file.parse(sheet_name, nrows=500).dropna(how='all').dropna(axis=1, how='all')
#     except:
#       self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')
#     self.df = clean_headers(self.df)
#     file_model.file.close()

#     self.df, self.links, self.initials, self.dicts = get_data(self.df, self.request, form.instance)

#     return form
#   def form_valid(self, form):
#     if not 'submit-btn' in self.request.POST or not self.request.POST['submit-btn'] == 'save':
#       return self.form_invalid(form)
#     self.setting = form.instance
#     self.setting.save()
#     for column_name, field_name in self.links.items():
#       link = Link(setting=self.setting, key=field_name, value=column_name, initial=str(self.initials[field_name]) if not self.initials[field_name] == '' else None)
#       link.save()
#       for key, value in self.dicts[field_name].items():
#         dict = Dict(link = link, key = str(key), value = str(value))
#         dict.save()
#     return super().form_valid(form)
#   def get_context_data(self, **kwargs):
#     context = super().get_context_data(**kwargs)
#     self.dict_tables = []
#     for key, value in LINKS.items():
#       if key == '': continue
#       self.dict_tables.append(get_dict_table(self.request, key, value))
#     context['dict_tables'] = self.dict_tables
#     return context

  
# class SettingUpdate(SingleTableMixin, UpdateView):
#   '''Обновление настройки <</setting/<int:id>/update/<int:f_id>/>>'''
#   model = Setting
#   form_class = SettingForm
#   template_name = 'supplier/setting/create.html'
#   prefix = 'setting-form'
#   pk_url_kwarg = 'id'
#   def get_success_url(self):
#     return reverse('supplier')
#   def get_table_class(self):
#     return get_link_create_table()
#   def get_table(self, **kwargs):
#     return super().get_table(**kwargs, columns=list(self.df.columns), links=self.links)
#   def get_table_data(self):
#     return self.df.to_dict('records')
#   def get_form(self):
#     form = super().get_form(form_class = self.form_class)
#     self.setting = form.instance
#     file_model = FileModel.objects.get(id=self.kwargs['f_id'])
#     excel_file = pd.ExcelFile(file_model.file)
#     choices = [(name, name) for name in excel_file.sheet_names]
#     form.fields['sheet_name'].choices = choices
#     try:
#       sheet_name = form.data['sheet_name']
#     except:
#       sheet_name = choices[0][0]
#     try:
#       self.df = excel_file.parse(sheet_name, nrows=500).dropna(how='all').dropna(axis=1, how='all')
#     except:
#       self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')
#     self.df = clean_headers(self.df)
#     file_model.file.close()

#     self.df, self.links, self.initials, self.dicts = get_data(self.df, self.request, self.setting)


#     if self.links == {}:
#       messages.info(self.request, 'Нажмите применить чтобы заработали замены')
#       for link in Link.objects.filter(setting__pk=self.setting.pk):
#         self.links[link.value] = link.key
#         self.initials[link.key] = link.initial


#     return form
#   def form_valid(self, form):
#     if not 'submit-btn' in self.request.POST or not self.request.POST['submit-btn'] == 'save':
#       return self.form_invalid(form)
#     self.setting = form.instance
#     for link in Link.objects.filter(setting=self.setting):
#       link.delete()
#     for column_name, field_name in self.links.items():
#       link = Link(setting=self.setting, key=field_name, value=column_name, initial=str(self.initials[field_name]) if not self.initials[field_name] == '' else None)
#       link.save()
#       for key, value in self.dicts[field_name].items():
#         dict = Dict(link = link, key = str(key), value = str(value))
#         dict.save()
#     return super().form_valid(form)
#   def get_context_data(self, **kwargs):
#     context = super().get_context_data(**kwargs)
#     self.dict_tables = []
#     for key, value in LINKS.items():
#       if key == '': continue
#       self.dict_tables.append(
#         get_dict_table(
#           self.request, 
#           key, 
#           value, 
#           Link.objects.filter(
#             setting=self.setting, 
#             key=key
#           ).first() if self.dicts=={} else None
#         )
#       )
#     context['dict_tables'] = self.dict_tables
#     return context


# class SettingDelete(DeleteView):
#   model = Setting
#   template_name = 'supplier/setting/confirm_delete.html'
#   pk_url_kwarg='id'
#   def get_success_url(self):
#     return f'''/supplier/{self.get_object().supplier.pk}/settings'''

# class SettingDetail(SingleTableView):
#   '''Отображает настройку поставщика <<setting/<int:id>/>>'''
#   model = Link
#   table_class = LinkListTable
#   template_name = 'supplier/setting/detail.html'
#   def get_table_data(self):
#     return Link.objects.filter(setting_id=self.kwargs['id'])
#   def get_context_data(self, **kwargs):
#     context = super().get_context_data(**kwargs)
#     context['setting_id'] = self.kwargs['id']
#     context['setting'] = Setting.objects.get(id=context['setting_id'])
#     return context

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
