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
from main_product_manager.models import MainProduct, MainProductLog, MP_PRICES, recalculate_search_vectors
from product_price_manager.models import PriceManager, PriceTag
from core.functions import extract_initial_from_post
from .models import DictItem
from .forms import *
from .tables import *
from .filters import *

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
    if not instance.setting:
      number = 0
      created = False
      while not created:
        try:
          anti_copy = f'({number})' if not number == 0 else ''
          setting = Setting.objects.create(
            name = os.path.splitext(os.path.basename(instance.file.path))[0] + anti_copy, 
            supplier = Supplier.objects.get(pk=self.kwargs.get('pk')))
          setting.sheet_name = pd.ExcelFile(instance.file, engine='calamine').sheet_names[0]
          setting.save()
          created = True
          instance.setting = setting
          messages.info(self.request, f"Новая настройка создана: {setting.name}")
        except:
          number += 1
          created = False
    if not instance.setting.sheet_name in pd.ExcelFile(instance.file, engine='calamine').sheet_names:
      messages.error(self.request, f'Нет листа {setting.sheet_name}')
      return self.form_invalid(form)
    for supplier_file in instance.setting.supplier_files.all():
      supplier_file.file.delete()
      supplier_file.delete()
    instance.save()
    if instance.setting.is_bound():
      return redirect(reverse('setting-upload', kwargs={'pk': instance.setting.pk, 'state':0}))
    else: 
      return redirect(reverse('setting-update', kwargs={'pk': instance.setting.pk}))

  def get_success_url(self):
    return reverse('supplier-upload', kwargs={'pk':self.kwargs.get('pk')})
  
def setting_upload(request, pk, state):
  setting = Setting.objects.get(pk=pk)
  if state == 0:
    return render(request, 'supplier_product/partials/load_partial.html', {'pk':pk, 'state':0})
  if setting.is_bound():
    products = load_setting(pk)
    messages.info(request, f"Загрузка файла через настройку {setting.name}. Обработано {len(products[0])} товаров. Добавлено {len(products[1])} товаров главного прайса")
  else:
    messages.error(request, f'Не указано поле артикула и\\или наименования')
  return HttpResponseClientRefresh()

class XMLTableView(TemplateView):
  template_name = 'supplier_product/partials/csv_table.html'
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      pk = self.kwargs.get('pk')
      context = super().get_context_data(**kwargs)
      df = get_df(self.kwargs.get('pk')).fillna('')
      page = int(self.request.GET.get('page', 1))
      items = Paginator(df.to_records(index=False), per_page=5).page(page)
      context['pk'] = pk
      context['items'] = items
      context['columns'] = get_df_sheet_names(pk=pk)
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
    form.fields['sheet_name'].choices = [(sheet_name, sheet_name) for sheet_name in get_df_sheet_names(self.kwargs.get('pk'))]
    return form
  def get_success_url(self):
    return reverse('setting-update', kwargs={'pk': self.kwargs.get('pk')})
  def form_valid(self, form):
    pk = self.kwargs.get('pk')
    setting = Setting.objects.get(pk=pk)
    post = self.request.POST

    if post.get('action', None) == 'delete':
      for mfile in setting.supplier_files.all():
        mfile.file.delete()
        mfile.delete()
      setting.delete()
      return HttpResponseClientRefresh()

    df = get_df(pk)

    if not setting.sheet_name == form.cleaned_data['sheet_name']:
      setting.sheet_name = form.cleaned_data['sheet_name']
      setting.save()
    
    link_formset = get_linkformset(post, pk)
    indicts = get_indicts(post, pk)
    if not link_formset.is_valid() :
      messages.error(self.request, f'Неоднозначная связь: Столбец\\знаение')
      return self.form_invalid(form)
    keys = [item['key'] for item in link_formset.cleaned_data if not item['key']=='']
    if not len(set(keys)) == len(keys):
      messages.error(self.request, f'Неоднозначная связь: Столбец\\знаение')
      return self.form_invalid(form)
    
    for i in range(len(link_formset.cleaned_data)):
      link = None
      key = link_formset.cleaned_data[i]['key']
      if not key or key=='' : continue
      link = Link.objects.get_or_create(setting=setting, key=key)[0]
      if indicts[key]['initial'].is_valid():
        link.initial = indicts[key]['initial'].cleaned_data['initial']
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
      return redirect(reverse('setting-upload', kwargs={'pk': setting.pk, 'state':0}))
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
  df = get_df(pk, nrows=None)
  for link in links:
    if link.value == '': continue
    if link.initial:
      df[link.value] = df[link.value].fillna(link.initial)
    for dict in link.dicts.all():
      df[link.value] = df[link.value].replace(dict.key, dict.value)
    df = df.rename(columns={link.value : link.key})
  if not 'article' in df.columns: return None
  df = df.replace('', np.nan)
  df = df.loc[:,[link.key for link in links if not link.key=='' and link.key in df.columns]]
  df = df.dropna(subset=['article'])
  for link in links:
    if link.key in df.columns and link.key in SP_NUMBERS:
      df[link.key] = pd.to_numeric(df[link.key], errors='coerce')
  df = df.dropna(subset=[link.key for link in links if not link.key=='article' and not link.key == 'name' and link.key in df.columns], how='all')
  df = df.replace({pd.NA: None, float('nan'): None})
  if 'manufacturer' in df.columns:
    df['manufacturer'] = df['manufacturer'].apply(lambda s: Manufacturer.objects.get_or_create(name=s)[0] if s else None)
  if 'discount' in df.columns:
    df['discount'] = df['discount'].apply(lambda s: Discount.objects.get_or_create(supplier=setting.supplier, name=s)[0] if s else None)
  if 'name' in df.columns:
    df = df.dropna(subset=['name'])
    df['main_product'] =  list(map(
      lambda row: MainProduct(
        supplier=setting.supplier,
        article=row.article,
        name=row.name,
        **{'manufacturer': row.manufacturer if 'manufacturer' in df.columns else None}
      ),
      df.itertuples(index=False)))
    
    mps = MainProduct.objects.bulk_create(
      df['main_product'].to_list(),
      
      update_conflicts=True,

      unique_fields=['supplier', 'article', 'name'],
      update_fields=['search_vector']
    )
    def get_spmodel(row):
      data = {
          link.key: Decimal(str(getattr(row, link.key))) if link.key in SP_NUMBERS else getattr(row, link.key)
          for link in links 
          if not link.key=='article' and not link.key == 'name' and link.key in df.columns
          and getattr(row, link.key)
        }
      if row.main_product:
        data['main_product'] = row.main_product
      return SupplierProduct(
        supplier=setting.supplier,
        article=row.article,
        name=row.name,
        **data)
    sp_model_instances = map(get_spmodel, df.itertuples(index=False))
    sp_update_fields = [link.key for link in links if not link.key=='article' and not link.key == 'name' and link.key in df.columns]
    sp_update_fields.append('updated_at')
    sps = SupplierProduct.objects.bulk_create(
      sp_model_instances, 
      update_conflicts=True, 
      update_fields=sp_update_fields,
      unique_fields=['supplier', 'article', 'name'])
    recalculate_search_vectors(MainProduct.objects.filter(pk__in=[mp.pk for mp in mps]))
    if 'stock' in df.columns:
      setting.supplier.stock_updated_at = timezone.now()
    if not set(SP_PRICES).intersection(set(df.columns)) == set():
      setting.supplier.price_updated_at = timezone.now()
    setting.supplier.save()
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
  
# Обработка продуктов


def delete_supplier_product(request, **kwargs):
  '''
  Подвязка к функции удаления на странице поставщика
  <<supplier-product/<int:id>/delete/>>
  '''
  product = SupplierProduct.objects.get(id=kwargs['id'])
  pk = product.supplier.pk
  product.delete()
  return redirect('supplier-detail', pk = pk)
