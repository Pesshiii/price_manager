# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404)
from django.utils import timezone
from django.template.loader import render_to_string
from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import (View,
                                  ListView,
                                  DetailView,
                                  CreateView,
                                  UpdateView,
                                  DeleteView,
                                  FormView,
                                  TemplateView)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from typing import Optional, Any, Dict, Iterable
from collections import defaultdict, OrderedDict
from django.db.models import Count, Prefetch
from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView, FilterMixin
from dal import autocomplete

# Импорты моделей, функций, форм, таблиц
from .models import *
from .functions import *
from .forms import *
from .tables import *
from .filters import *

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math


class AppLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            existing_classes = field.widget.attrs.get('class', '')
            classes = [cls for cls in existing_classes.split() if cls]
            if 'form-control' not in classes:
                classes.append('form-control')
            field.widget.attrs['class'] = ' '.join(classes) if classes else 'form-control'
        return form


class AppLogoutView(LogoutView):
    next_page = 'login'

class CategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        
        qs = Category.objects.all()

        if self.q:
            qs = qs.filter(name__icontains=self.q)

        return qs


def build_category_tree(categories):
  children_map = defaultdict(list)
  for category in categories:
    children_map[category.parent_id].append(category)
  for siblings in children_map.values():
    siblings.sort(key=lambda item: item.name.lower())
  def build_nodes(parent_id):
    nodes = []
    for category in children_map.get(parent_id, []):
      nodes.append({
          'category': category,
          'children': build_nodes(category.id)
      })
    return nodes
  return build_nodes(None)


def _collect_int_values(values):
  result = set()
  for value in values:
    try:
      result.add(int(value))
    except (TypeError, ValueError):
      continue
  return result


def _expand_category_ids_with_ancestors(category_ids):
  expanded_ids = set(category_ids)
  to_process = {category_id for category_id in expanded_ids if category_id is not None}
  while to_process:
    parents = set(
        Category.objects
        .filter(id__in=to_process)
        .values_list('parent_id', flat=True)
    )
    parents.discard(None)
    new_ids = parents - expanded_ids
    if not new_ids:
      break
    expanded_ids.update(new_ids)
    to_process = new_ids
  expanded_ids.discard(None)
  return expanded_ids


def _get_search_filtered_queryset(request):
  filter_data = request.GET.copy()
  for field in ('category', 'supplier', 'manufacturer'):
    filter_data.pop(field, None)
  filter_data.pop('page', None)
  filterset = MainProductFilter(data=filter_data, queryset=MainProduct.objects.all())
  return filterset.qs


def get_main_filter_context(request):
  filterset = MainProductFilter(data=request.GET or None, queryset=MainProduct.objects.all())
  filter_form = filterset.form

  queryset = _get_search_filtered_queryset(request)

  selected_supplier_ids = _collect_int_values(request.GET.getlist('supplier'))
  selected_manufacturer_ids = _collect_int_values(request.GET.getlist('manufacturer'))
  selected_category_ids = _collect_int_values(request.GET.getlist('category'))

  supplier_ids = set(queryset.values_list('supplier_id', flat=True))
  supplier_ids.discard(None)
  supplier_ids.update(selected_supplier_ids)

  manufacturer_ids = set(queryset.values_list('manufacturer_id', flat=True))
  manufacturer_ids.discard(None)
  manufacturer_ids.update(selected_manufacturer_ids)

  category_ids = set(queryset.values_list('category_id', flat=True))
  category_ids.discard(None)
  category_ids.update(selected_category_ids)
  category_ids = _expand_category_ids_with_ancestors(category_ids)

  supplier_queryset = Supplier.objects.filter(id__in=supplier_ids).order_by('name') if supplier_ids else Supplier.objects.none()
  manufacturer_queryset = Manufacturer.objects.filter(id__in=manufacturer_ids).order_by('name') if manufacturer_ids else Manufacturer.objects.none()
  category_queryset = Category.objects.filter(id__in=category_ids).select_related('parent') if category_ids else Category.objects.none()

  filter_form.fields['supplier'].queryset = supplier_queryset
  filter_form.fields['manufacturer'].queryset = manufacturer_queryset
  filter_form.fields['category'].queryset = category_queryset

  available_suppliers = list(supplier_queryset)
  available_manufacturers = list(manufacturer_queryset)

  selected_categories = {str(value) for value in request.GET.getlist('category') if value}

  category_tree = build_category_tree(list(category_queryset))

  return {
      'filter_form': filter_form,
      'category_tree': category_tree,
      'selected_categories': selected_categories,
      'available_suppliers': available_suppliers,
      'available_manufacturers': available_manufacturers,
  }


class MainPage(SingleTableMixin, FilterView):
  model = MainProduct
  filterset_class = MainProductFilter
  table_class = MainProductListTable
  template_name = 'main/main.html'
  table_pagination = False

  def get_table(self, **kwargs):
    return super().get_table(**kwargs, request=self.request)

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    filter_context = get_main_filter_context(self.request)
    context.update(filter_context)

    filterset = context.get('filter')
    category_tables = []

    if filterset is not None:
      filtered_records = filterset.qs.select_related('category')

      if len(filtered_records) > 1000:
        category_table = self.table_class(filtered_records, request=self.request)
        RequestConfig(self.request).configure(category_table)
        category_tables.append({
            'category': Category.objects.none(),
            'table': category_table,
        })
      else:
        grouped_records = OrderedDict()
        grouped_records[None] = {
                  'category': Category.objects.none(),
                  'records': list(filtered_records.filter(category__isnull=True))
              }
        for category in Category.objects.all():
          if not list(filtered_records.filter(category=category)) == []:
            grouped_records[category.pk] = {
                  'category': category,
                  'records': list(filtered_records.filter(category=category))
              }
        sorted_groups = sorted(
            grouped_records.values(),
            key=lambda item: (
                item['category'] is None,
                (item['category'].name.lower() if item['category'] else ''),
            )
        )

        for group in sorted_groups:
          category_table = self.table_class(group['records'], request=self.request)
          RequestConfig(self.request, paginate=False).configure(category_table)
          category_tables.append({
              'category': group['category'],
              'table': category_table,
          })

    context['category_tables'] = category_tables

    filter_form = filter_context['filter_form']
    dynamic_url = reverse('main-filter-options')
    hx_attrs = {
        'hx-get': dynamic_url,
        'hx-target': '#filters-update-sink',
        'hx-include': '#main-filter-form',
    }

    search_field = filter_form.fields['search']
    search_field.widget.attrs.update({
        **hx_attrs,
        'hx-trigger': 'keyup changed delay:500ms',
        'autocomplete': 'off',
    })

    anti_search_field = filter_form.fields['anti_search']
    anti_search_field.widget.attrs.update({
        **hx_attrs,
        'hx-trigger': 'keyup changed delay:500ms',
        'autocomplete': 'off',
    })

    if 'available' in filter_form.fields:
      filter_form.fields['available'].widget.attrs.update({
          **hx_attrs,
          'hx-trigger': 'change',
      })

    context['table_update_url'] = reverse('main-table')
    return context


class MainFilterOptionsView(View):
  template_name = 'main/includes/dynamic_filters.html'

  def get(self, request, *args, **kwargs):
    context = get_main_filter_context(request)
    return render(request, self.template_name, context)


class MainTableView(MainPage):
  template_name = 'main/includes/table.html'

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
  fields = SUPPLIER_SPECIFIABLE_FIELDS
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
  fields = SUPPLIER_SPECIFIABLE_FIELDS
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
    if not column in df.columns:
      df[column] = None
    if field == 'article':
      df=df[df[column].notnull()]
    if field == 'name' and setting.differ_by_name:
      df=df[df[column].notnull()]
    if field in SP_PRICES and setting.priced_only:
      df = df[df[column].notnull()]
    buf: pd.Series = df[column]
    buf = buf.fillna(initials[field])
    buf = buf.astype(str)
    buf = buf.replace(dicts[field], regex=True)
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
    if not value or  value == '':
      num = 0
    else:
      num = float(value)
    return 0 if num < 0 else num
  if field in SP_INTEGERS:
    if not value or  value == '':
      num = 0
    else:
      num = int(float(value))
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
      if not key in initials or initials[key] == '': continue
      while buf in df.columns:
        buf += ' Копия'
      links[buf] = key

      
  dicts = {}
  for column_name, field_name in links.items():
    if not column_name in df.columns:
      df[column_name] = None
    initials[field_name] = initials[field_name]
    dicts[field_name] = {}
    for item in extract_initial_from_post(
                post, 
                prefix=f'dict-form-{field_name}', 
                data={'key':'', 'value':''}
                ):
      if not item['key'] in dicts[field_name]:
        dicts[field_name][item['key']] = item['value']
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
    try:
      self.df = excel_file.parse(sheet_name, nrows=500).dropna(how='all').dropna(axis=1, how='all')
    except:
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
    try:
      self.df = excel_file.parse(sheet_name, nrows=500).dropna(how='all').dropna(axis=1, how='all')
    except:
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
  initials = {link.key: link.initial if link.initial else '' for link in Link.objects.filter(setting=setting)}
  dicts = {link.key: {item.key: item.value for item in Dict.objects.filter(link=link)} for link in Link.objects.filter(setting=setting)}
  for key, value in LINKS.items():
    if key == '': continue
    buf = value
    if key not in links.values():
      if not key in initials or initials[key] == '': continue
      while buf in df.columns:
        buf += ' Копия'
      links[buf] = key
  rev_links = {value: key for key, value in links.items()}
  df = get_df(df, links, initials, dicts, setting)
  if setting.differ_by_name:
    df = df.drop_duplicates(subset=[rev_links['name'], rev_links['article']])
  else:
    df = df.drop_duplicates(subset=[rev_links['article']])
  return df, links, initials, dicts

class SettingDisplay(DetailView):
  '''Проверка данных перед загрузкой <<setting/<int:id>/upload/<int:f_id>/>>'''
  model = Setting
  template_name='supplier/setting/upload.html'
  pk_url_kwarg = 'id'
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    setting: Setting = self.get_object()
    context['setting'] = setting
    context['supplier'] = setting.supplier
    file_model = FileModel.objects.get(id=self.kwargs['f_id'])
    try:
      excel_file = pd.ExcelFile(file_model.file)
      try:
        self.df = excel_file.parse(setting.sheet_name, nrows=500).dropna(how='all').dropna(axis=1, how='all')
      except:
        self.df = excel_file.parse(setting.sheet_name).dropna(how='all').dropna(axis=1, how='all')
      self.df = clean_headers(self.df)
      file_model.file.close()
      self.df, self.links, self.initials, self.dicts = get_upload_data(setting, self.df)
      table = get_upload_list_table()(links=self.links, data=self.df.to_dict('records'))
      RequestConfig(self.request, paginate=True).configure(table)
      context['table'] = table
    except BaseException as ex:
      messages.error(self.request, ex)
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

def clean_column(column):
  column = column.str.strip()

  # # Convert to lowercase/uppercase
  # column = column.str.lower()
  # column = column.str.upper()

  # Remove special characters
  column = column.str.replace(r'[^\w\s]', '', regex=True)

  # Replace multiple spaces with single space
  column = column.str.replace(r'\s+', ' ', regex=True)
  return column

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
    df[rev_links['discounts']] = clean_column(df[rev_links['discounts']])
    discs = {disc: Discount.objects.get_or_create(supplier=supplier, name=disc)[0] for disc in df[rev_links['discounts']].unique()}
  cats = {}
  if 'category' in rev_links:
    cats = {cat: Category.objects.get_or_create(name=cat)[0] for cat in df[rev_links['category']].unique()}
  
  mans = {}
  if 'manufacturer' in rev_links:
    mans = {man: Manufacturer.objects.get_or_create(name=man)[0] for man in df[rev_links['manufacturer']].unique()}
  
  sp = []
  mp = []
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
      if  setting.differ_by_name and  'name' in rev_links:
        product, created = SupplierProduct.objects.get_or_create(supplier=supplier, article=row[rev_links['article']],
                                                                  name=row[rev_links['name']])
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
            try:
              setattr(product, field, get_safe(row[column], float))
            except BaseException as ex:
              messages.error(request, f'Ошибка конвертации цены {row[column]} в поле {field}: {ex}')
            continue
          try:
            setattr(product, field, convert_sp(row[column], field))
          except BaseException as ex:
            messages.error(request, f'Ошибка конвертации {row[column]} в поле {field}: {ex}')
        if setting.update_main:
          main_product, main_created = MainProduct.objects.get_or_create(supplier=supplier, article=product.article,
                                                              name=product.name)
          text = main_product._build_search_text()
          main_product.search_vector = SearchVector(Value(text), config='russian')
          if main_created and 'category' in rev_links:
            main_product.category = product.category
          if main_created and 'manufacturer' in rev_links:
            main_product.manufacturer = product.manufacturer
          product.main_product = main_product
          mp.append(main_product)
        sp.append(product)
        overall += 1
      except BaseException as ex:
        exs.append(ex)

  MainProduct.objects.bulk_update(mp, fields=['supplier', 'article', 'name', 'search_vector', 'manufacturer'])
  SupplierProduct.objects.bulk_update(sp, fields=[field for field in links.values() if not field=='discounts'])
  SupplierProduct.objects.bulk_update(sp, fields=['supplier_price', 'rrp', 'main_product'])
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
    if not cleaned_data['has_rrp'] is None:
      if cleaned_data['has_rrp']:
        products = products.filter(rrp__gt=0)
      else:
        products = products.filter(rrp=0)

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
    if price_to and price_to==0:
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
    if cleaned_data['has_rrp'] is None:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp__isnull=True)|Q(has_rrp=True)|Q(has_rrp=False))
    elif cleaned_data['has_rrp']:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp=True)|Q(has_rrp__isnull=True))
    else:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp=False)|Q(has_rrp__isnull=True))
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
  

class PriceManagerUpdate(SingleTableMixin, UpdateView):
  '''Обновление Наценки <<price-manager/<int:id>/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  table_class = SupplierProductPriceManagerTable
  success_url = '/price-manager/'
  template_name = 'price_manager/create.html'
  pk_url_kwarg = 'id'
  def get_success_url(self):
    return f'/price-manager'
  def get_table_data(self):
    products = SupplierProduct.objects.all()
    if not hasattr(self, 'cleaned_data'):
      return products
    cleaned_data = self.cleaned_data
    products = products.filter(
      supplier=cleaned_data['supplier'])
    if not cleaned_data['has_rrp'] is None:
      if cleaned_data['has_rrp']:
        products = products.filter(rrp__gt=0)
      else:
        products = products.filter(rrp=0)

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
    if not form.fields['discounts'].choices == choices:
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
    conf_price_manager = conf_price_manager.filter(~Q(id=self.kwargs.get('id')))
    if cleaned_data['discounts']:
      conf_price_manager = conf_price_manager.filter(
      Q(discounts__in=cleaned_data['discounts'])|
      Q(discounts__isnull=True))
    if cleaned_data['has_rrp'] is None:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp__isnull=True)|Q(has_rrp=True)|Q(has_rrp=False))
    elif cleaned_data['has_rrp']:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp=True)|Q(has_rrp__isnull=True))
    else:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp=False)|Q(has_rrp__isnull=True))
    conf_price_manager = conf_price_manager.filter(
      dest=cleaned_data['dest'])
    conf_price_manager = conf_price_manager.filter(supplier=cleaned_data['supplier'])
    if conf_price_manager.exists():
      messages.error(self.request, f'Пересечение с другой наценкой: {conf_price_manager.first().name}')
      return self.form_invalid(form)
    if not self.request.POST.get('btn') == 'save': return self.form_invalid(form)
    form.save()
    messages.success(self.request, 'Наценка успешно обновлена')
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
  if not price_manager.has_rrp is None:
    if price_manager.has_rrp:
      products = products.filter(rrp__gt=0)
    else:
      products = products.filter(rrp=0)

  discounts = list(price_manager.discounts.values_list('id'))
  if not discounts == []:
    products = products.filter(
      discounts__in=discounts)
    


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
              product if price_manager.source in SP_PRICES else main_product, price_manager.source, 0)*main_product.supplier.currency.value*(1+price_manager.markup/100)+price_manager.increase))
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
  """Обновляет остатки и применяет наценки в MainProduct из SupplierProduct"""
  updated = 0
  errors = 0

  supplier_products = SupplierProduct.objects.select_related("main_product").all()

  mps = []

  
  has_rrp = Discount.objects.filter(name="Есть РРЦ").first()
  no_rrp = Discount.objects.filter(name="Нет РРЦ").first()

  for sp in supplier_products:
    try:
      if not sp.main_product:
        continue  # пропускаем без связи
      change = False
      mp = sp.main_product
      if not mp.stock == sp.stock:
        mp.stock = sp.stock
        mp.stock_updated_at = sp.supplier.stock_updated_at
        change = True
      text = mp._build_search_text()
      mp.search_vector = SearchVector(Value(text), config='russian')
      # if change:
      mps.append(mp)

      if has_rrp and sp.discounts.contains(has_rrp):
        sp.discounts.remove(has_rrp)
        sp.save()
      if no_rrp and sp.discounts.contains(no_rrp):
        sp.discounts.remove(no_rrp)
        sp.save()
    except Exception as ex:
      errors += 1
      messages.error(request, f"Ошибка при обновлении {sp}: {ex}")
  updated = MainProduct.objects.bulk_update(mps, ['stock', 'stock_updated_at', 'manufacturer', 'category', 'search_vector'])
  messages.success(request, f"Остатки обновлены у {updated} товаров, ошибок: {errors}")
  for price_manager in PriceManager.objects.all():
    if has_rrp and price_manager.discounts.contains(has_rrp):
      price_manager.discounts.remove(has_rrp)
      price_manager.has_rrp = True
      price_manager.save()
    if no_rrp and price_manager.discounts.contains(no_rrp):
      price_manager.discounts.remove(no_rrp)
      price_manager.has_rrp = False
      price_manager.save()
    apply_price_manager(price_manager)
  if has_rrp:
    has_rrp.delete()
  if no_rrp:
    no_rrp.delete()
  messages.success(request, 'Наценки применены')
  return redirect('main')


class ShoppingTabListView(LoginRequiredMixin, TemplateView):
  template_name = 'shopping_tab/list.html'
  form_class = ShopingTabCreateForm

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    form = kwargs.get('form')
    context['form'] = form if form is not None else self.form_class()
    context['tabs'] = (
      ShopingTab.objects
      .filter(user=self.request.user)
      .annotate(product_count=Count('products', distinct=True))
      .order_by('name')
    )
    context['products'] = {tab.name: [product for product in tab.products.all()] for tab in context['tabs']}
    return context

  def post(self, request, *args, **kwargs):
    form = self.form_class(request.POST)
    if form.is_valid():
      name = form.cleaned_data['name']
      if ShopingTab.objects.filter(user=request.user, name=name).exists():
        form.add_error('name', 'Корзина с таким названием уже существует.')
      else:
        tab = form.save(commit=False)
        tab.user = request.user
        tab.save()
        messages.success(request, 'Корзина создана.')
        return redirect('shopping-tab-list')
    return self.render_to_response(self.get_context_data(form=form))


class ShoppingTabDeleteView(LoginRequiredMixin, View):
  def post(self, request, pk):
    tab = get_object_or_404(ShopingTab, pk=pk, user=request.user)
    tab.delete()
    messages.success(request, 'Корзина удалена.')
    return redirect('shopping-tab-list')


class ShoppingTabDetailView(LoginRequiredMixin, UpdateView):
  model = ShopingTab
  form_class = ShopingTabUpdateForm
  template_name = 'shopping_tab/detail.html'
  context_object_name = 'tab'

  def get_queryset(self):
    return super().get_queryset().filter(user=self.request.user)

  def form_valid(self, form):
    messages.success(self.request, 'Корзина обновлена.')
    return super().form_valid(form)

  def get_success_url(self):
    return reverse('shopping-tab-detail', kwargs={'pk': self.object.pk})

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['products'] = (
      self.object.products.select_related('main_product')
      .order_by('name')
    )
    return context


class ShoppingTabProductCreateView(LoginRequiredMixin, View):
  template_name = 'shopping_tab/product_form.html'
  form_class = AlternateProductForm

  def dispatch(self, request, *args, **kwargs):
    self.tab = get_object_or_404(ShopingTab, pk=kwargs['tab_pk'], user=request.user)
    return super().dispatch(request, *args, **kwargs)

  def get_context(self, form):
    return {
      'form': form,
      'tab': self.tab,
      'is_update': False,
    }

  def get(self, request, *args, **kwargs):
    form = self.form_class()
    return render(request, self.template_name, self.get_context(form))

  def post(self, request, *args, **kwargs):
    form = self.form_class(request.POST)
    if form.is_valid():
      name = form.cleaned_data['name']
      main_product = form.cleaned_data.get('main_product')
      alternate_product, _ = AlternateProduct.objects.get_or_create(
        name=name,
        main_product=main_product,
      )
      if self.tab.products.filter(pk=alternate_product.pk).exists():
        messages.info(request, 'Этот товар уже есть в корзине.')
      else:
        self.tab.products.add(alternate_product)
        messages.success(request, 'Товар добавлен в корзину.')
      return redirect('shopping-tab-detail', pk=self.tab.pk)
    return render(request, self.template_name, self.get_context(form))


class ShoppingTabProductUpdateView(LoginRequiredMixin, UpdateView):
  model = AlternateProduct
  form_class = AlternateProductForm
  template_name = 'shopping_tab/product_form.html'
  context_object_name = 'alternate_product'
  pk_url_kwarg = 'product_pk'

  def dispatch(self, request, *args, **kwargs):
    self.tab = get_object_or_404(ShopingTab, pk=kwargs['tab_pk'], user=request.user)
    return super().dispatch(request, *args, **kwargs)

  def get_queryset(self):
    return super().get_queryset().filter(shoping_tabs=self.tab)

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['tab'] = self.tab
    context['is_update'] = True
    return context

  def form_valid(self, form):
    messages.success(self.request, 'Данные товара обновлены.')
    return super().form_valid(form)

  def get_success_url(self):
    return reverse('shopping-tab-detail', kwargs={'pk': self.tab.pk})


class ShoppingTabProductDeleteView(LoginRequiredMixin, View):
  def post(self, request, tab_pk, pk):
    tab = get_object_or_404(ShopingTab, pk=tab_pk, user=request.user)
    product = get_object_or_404(AlternateProduct, pk=pk, shoping_tabs=tab)
    tab.products.remove(product)
    if not product.shoping_tabs.exists():
      product.delete()
    messages.success(request, 'Товар удален из корзины.')
    return redirect('shopping-tab-detail', pk=tab.pk)


class ShoppingTabSelectionView(LoginRequiredMixin, TemplateView):
  template_name = 'shopping_tab/add_to_tab_modal.html'

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    product = get_object_or_404(MainProduct, pk=self.kwargs['product_id'])
    tabs = (
      ShopingTab.objects
      .filter(user=self.request.user)
      .annotate(product_count=Count('products', distinct=True))
      .prefetch_related(
        Prefetch(
          'products',
          queryset=AlternateProduct.objects.select_related('main_product').order_by('name')
        )
      )
      .order_by('name')
    )
    existing_tab_ids = set(
      AlternateProduct.objects
      .filter(main_product=product, shoping_tabs__user=self.request.user)
      .values_list('shoping_tabs__id', flat=True)
    )
    context.update({
      'product': product,
      'tabs': tabs,
      'existing_tab_ids': existing_tab_ids,
    })
    return context


class ShoppingTabAddProductView(LoginRequiredMixin, View):
  template_name = 'shopping_tab/add_to_tab_modal_result.html'

  def post(self, request, tab_pk, product_id):
    tab = get_object_or_404(ShopingTab, pk=tab_pk, user=request.user)
    product = get_object_or_404(MainProduct, pk=product_id)
    alternate_product_id = request.POST.get('alternate_product_id')
    if alternate_product_id:
      alternate_product = get_object_or_404(
        AlternateProduct,
        pk=alternate_product_id,
        shoping_tabs=tab,
      )
      already_linked = alternate_product.main_product_id == product.pk
      if not already_linked:
        (tab.products
         .filter(main_product=product)
         .exclude(pk=alternate_product.pk)
         .update(main_product=None))
        alternate_product.main_product = product
        alternate_product.save(update_fields=['main_product'])
        status = 'success'
        message_text = (
          f'Товар связан с «{alternate_product.name}» в корзине «{tab.name}».')
      else:
        status = 'info'
        message_text = 'Выбранный товар уже связан с этой позицией корзины.'
    else:
      if tab.products.filter(main_product=product).exists():
        status = 'info'
        message_text = 'Товар уже связан с выбранной корзиной.'
      else:
        alternate_product, created = AlternateProduct.objects.get_or_create(
          name=product.name,
          main_product=product,
        )
        tab.products.add(alternate_product)
        status = 'success'
        if created:
          message_text = f'Товар добавлен в корзину «{tab.name}».'
        else:
          message_text = f'Товар привязан к корзине «{tab.name}».'
    context = {
      'tab': tab,
      'product': product,
      'status': status,
      'message': message_text,
    }
    return render(request, self.template_name, context)

