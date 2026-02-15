# Импорты из django
from django.contrib import messages
from django.contrib.postgres.search import SearchVector
from django.conf import settings
from django.db.models import ExpressionWrapper, Q, BooleanField, Value
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404)
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.generic import (View, TemplateView,
                                  DetailView,
                                  CreateView,
                                  UpdateView,
                                  DeleteView)
from django.core.paginator import Paginator
 


from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh, retarget
from django.template.context_processors import csrf
from crispy_forms.utils import render_crispy_form

# Импорты моделей, функций, форм, таблиц
from product_price_manager.models import PriceManager, PriceTag
from core.functions import extract_initial_from_post
from supplier_manager.forms import SupplierForm
from .models import DictItem
from .forms import *
from .tables import *
from .filters import *

import io, os
from typing import Dict, Any
import pandas as pd
import re

from .functions import *

class SupplierDetail(SingleTableMixin, FilterView):
  '''
  Таблица отображения товаров на странице поставщиков
  <<supplier/<int:id>/>>
  '''

  model = SupplierProduct
  table_class = SupplierProductListTable
  filterset_class = SupplierProductFilter
  template_name = 'supplier/detail.html'
  def get_filterset_kwargs(self, filterset_class):
    kwargs = super().get_filterset_kwargs(filterset_class)
    kwargs['pk'] = self.kwargs.get('pk', None)
    return kwargs
  def get(self, request, *args, **kwargs):
    self.supplier = Supplier.objects.get(pk=self.kwargs.get('pk', None))
    if self.request.htmx:
      self.template_name = 'supplier\partials\detail_products_table_partial.html'
    return super().get(request, *args, **kwargs)
  def post(self, request, *args, **kwargs):
    self.supplier = Supplier.objects.get(pk=self.kwargs.get('pk', None))
    form = SupplierForm(request.POST, instance=self.supplier)
    if form.is_valid():
      form.save()
      messages.success(request, 'Настройки поставщика сохранены')
    else:
      messages.error(request, 'Не удалось сохранить настройки поставщика')
    return redirect(f"{reverse('supplier-detail', kwargs={'pk': self.supplier.pk})}#supplier-settings")
  def get_table_data(self):
    return super().get_table_data().filter(supplier=self.supplier)
  def get_table(self, **kwargs):
    selected_columns = self.request.GET.getlist('columns')
    return super().get_table(**kwargs, selected_columns=selected_columns)
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['supplier'] = self.supplier
    context['column_groups'] = SP_AVAILABLE_COLUMN_GROUPS
    selected_columns = self.request.GET.getlist('columns')
    context['selected_columns'] = selected_columns if selected_columns else SP_DEFAULT_VISIBLE_COLUMNS
    context['supplier_form'] = SupplierForm(instance=self.supplier)
    pms = PriceManager.objects.filter(supplier=self.supplier)
    context['pricemanagers'] = pms
    return context

def copy_to_main(request, pk, state):
  if not request.htmx:
    redirect('supplier-update', pk=pk)
  if state == 0:
    url = reverse('supplier-copymain', kwargs={'pk':pk, 'state':1})
    return render(request, 'supplier_product/partials/load_partial.html', {'url':url})
  products = SupplierProductFilter(request.GET,pk=pk).qs.select_related('main_product', 'supplier').filter(supplier=pk)
  to_create = products.filter(main_product__isnull=True).count()
  def get_mp(sp: SupplierProduct):
    mp = MainProduct(supplier=sp.supplier, article=sp.article, name=sp.name, description=sp.description, manufacturer=sp.manufacturer, category=sp.category)
    sp.main_product = mp
    return mp
  mp_map = map(get_mp, products)
  mp_list = MainProduct.objects.bulk_create(mp_map, update_conflicts=True, unique_fields=['supplier', 'article', 'name'], update_fields=['manufacturer', 'category', 'description'])
  mps = MainProduct.objects.filter(pk__in=[mp.pk for mp in mp_list])
  products.bulk_update(products, fields=['main_product'])
  recalculate_search_vectors(mps)
  messages.info(request, f'Обработано товаров ГП {len(mps)}. Создано новых: {to_create}')
  return HttpResponseClientRedirect(reverse('supplier-detail', kwargs={'pk':pk}))

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
          messages.info(self.request, f"Новая настройка создана: {instance.setting.name}")
        except BaseException as ex:
          print(ex)
          number += 1
          created = False
    if not instance.setting.sheet_name in pd.ExcelFile(instance.file, engine='calamine').sheet_names:
      messages.error(self.request, f'Нет листа {instance.setting.sheet_name}')
      return self.form_invalid(form)
    for supplierfile in instance.setting.supplierfiles.all():
      supplierfile.file.delete()
      supplierfile.delete()
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
    url = reverse('setting-upload', kwargs={'pk':pk, 'state':1})
    return render(request, 'supplier_product/partials/load_partial.html', {'url':url})
  if setting.is_bound():
    products = load_setting(pk)
    if products is None:
      messages.info(request, "Нет связок")
    else:
      messages.info(request, f"Загрузка файла через настройку {setting.name}. Обработано {len(products)} товаров.")
  else:
    messages.error(request, f'Не указано поле артикула и\\или наименования')
  return HttpResponseClientRefresh()

class XMLTableView(TemplateView):
  template_name = 'supplier_product/partials/csv_table.html'
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      pk = self.kwargs.get('pk')
      context = super().get_context_data(**kwargs)
      df = get_df(self.kwargs.get('pk'))
      if df is None:
        return context
      df = df.fillna('')
      page = int(self.request.GET.get('page', 1))
      items = Paginator(df.to_records(index=False), per_page=5).page(page)
      context['pk'] = pk
      context['items'] = items
      context['columns'] = get_df_sheet_names(pk=pk)
      context['page'] = page
      return context
  
class SettingUpdate(UpdateView):
  model = Setting
  form_class = SettingForm
  template_name = "supplier_product/setting_update.html"
  def get(self, request, *args, **kwargs):
    pk = self.kwargs.get('pk')
    setting = Setting.objects.get(pk=pk)
    if setting.supplierfiles.first() is None or setting.supplierfiles.first().file is None:
      messages.error(request, 'Файл не найден')
    return super().get(request, *args, **kwargs)
  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['pk'] = self.kwargs.get('pk')
    return kwargs
  def get_form(self):
    form = super().get_form(self.form_class)
    pk = self.kwargs.get('pk')
    setting = Setting.objects.get(pk=pk)
    sheet_names = get_df_sheet_names(self.kwargs.get('pk'))
    if sheet_names:
      form.fields['sheet_name'].choices = [(sheet_name, sheet_name) for sheet_name in sheet_names]
    else:
      form.fields['sheet_name'].choices = [(setting.sheet_name, setting.sheet_name)]
    return form
  def get_success_url(self):
    return reverse('setting-update', kwargs={'pk': self.kwargs.get('pk')})
  def form_valid(self, form):
    pk = self.kwargs.get('pk')
    setting = Setting.objects.get(pk=pk)
    post = self.request.POST

    if post.get('action', None) == 'delete':
      for mfile in setting.supplierfiles.all():
        if not mfile.file is None:
          mfile.file.delete()
        mfile.delete()
      setting.delete()
      return HttpResponseClientRefresh()

    
    if not setting.name == form.cleaned_data['name']:
      setting.name = form.cleaned_data['name']
      setting.save()
    if not setting.sheet_name == form.cleaned_data['sheet_name']:
      setting.sheet_name = form.cleaned_data['sheet_name']
      setting.save()
      return redirect(reverse('setting-update', kwargs={'pk': pk}))
    if not setting.create_new == form.cleaned_data['create_new']:
      setting.create_new = form.cleaned_data['create_new']
      setting.save()
    
    df = get_df(pk)
    if df is None:
      messages.error(self.request, f'Пустой лист или неподходящая структура')
      return self.form_invalid(form)

    link_formset = get_linkformset(post, pk)
    indicts = get_indicts(post, pk)
    if not link_formset.is_valid() :
      messages.error(self.request, f'Что-то пошло не так')
      return HttpResponseClientRefresh()
    keys = [item['key'] for item in link_formset.cleaned_data if not item['key'] is None and not item['key']=='']
    if not len(set(keys)) == len(keys):
      messages.error(self.request, f'Неоднозначная связь: Столбец\\знаение')
      return self.form_invalid(form)
    setting.links.all().delete()
    for i in range(len(link_formset.cleaned_data)):
      link = None
      key = link_formset.cleaned_data[i]['key']
      if not key or key=='' : continue
      link = Link.objects.get_or_create(setting=setting, key=key)[0]
      link.value = df.columns[i]
      link.save()
    for link, value in LINKS.items():
      if link == '': continue
      if indicts[link]['dict_formset'].is_valid():
        mlink = Link.objects.get_or_create(setting=setting, key=link)[0]
        if indicts[link]['initial'].is_valid() and not indicts[link]['initial'].cleaned_data['initial'] == '':
          mlink.initial = indicts[link]['initial'].cleaned_data['initial']
          mlink.save()
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
