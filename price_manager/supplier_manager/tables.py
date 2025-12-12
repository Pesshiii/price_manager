from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from core.functions import *
from .forms import *

import pandas as pd

class SupplierListTable(tables.Table):
  '''Таблица отображаемая на странице Поставщики'''
  actions = tables.TemplateColumn(
    template_name='supplier/actions.html',
    orderable=False,
    verbose_name='Действия'
  )
  basic_price = tables.Column(
    empty_values=(),
    orderable=False,
    verbose_name='Базовая цена')
  m_price = tables.Column(
    empty_values=(),
    orderable=False,
    verbose_name='Цена ИМ')
  wholesale_price = tables.Column(
    empty_values=(),
    orderable=False,
    verbose_name='Оптовая цена')
  name = tables.LinkColumn('supplier-detail', args=[tables.A('pk')])
  class Meta:
    model = Supplier
    fields = ['name', 'price_updated_at', 'stock_updated_at', 'basic_price', 'm_price', 'wholesale_price']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
  def __init__(self, data=None, order_by=None, orderable=None, empty_text=None, exclude=None, attrs=None, row_attrs=None, pinned_row_attrs=None, sequence=None, prefix=None, order_by_field=None, page_field=None, per_page_field=None, template_name=None, default=None, request=None, show_header=None, show_footer=True, extra_columns=None):
    super().__init__(data, order_by, orderable, empty_text, exclude, attrs, row_attrs, pinned_row_attrs, sequence, prefix, order_by_field, page_field, per_page_field, template_name, default, request, show_header, show_footer, extra_columns)
    self.mps = MainProduct.objects.all().prefetch_related('supplier')
  def render_name(self, record):
    now = timezone.now()
    try:
      danger = (now - record.stock_updated_at).days >= TIME_FREQ[record.stock_update_rate] or (now - record.price_updated_at).days >= TIME_FREQ[record.price_update_rate]
    except:
      danger = False
    color = 'danger' if danger else 'success'
    return format_html(f'''<span class=" status-indicator bg-{color} rounded-circle"></span> {record.name}({self.mps.filter(supplier=record.pk).count()})''')
  def render_basic_price(self, record):
    mps = self.mps.filter(supplier=record.pk)
    n_mps = mps.filter(basic_price__isnull=False)
    return f'{n_mps.count()} / {mps.count()-n_mps.count()}'
  def render_m_price(self, record):
    mps = self.mps.filter(supplier=record.pk)
    n_mps = mps.filter(m_price__isnull=False)
    return f'{n_mps.count()} / {mps.count()-n_mps.count()}'
  def render_wholesale_price(self, record):
    mps = self.mps.filter(supplier=record.pk)
    n_mps = mps.filter(wholesale_price__isnull=False)
    return f'{n_mps.count()} / {mps.count()-n_mps.count()}'
  

class ManufacturerListTable(tables.Table):
  '''Таблица Производителей отображаемая на странице Производители'''
  name = tables.LinkColumn('manufacturer-detail', args=[tables.A('pk')])
  class Meta:
    model = Manufacturer
    fields = [field for field, value in get_field_details(model).items()
              if not '_ptr' in field]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
    
class ManufacturerDictListTable(tables.Table):
  '''Таблица Словаря отображаемая на странице Производитель/Словарь'''
  class Meta:
    model = ManufacturerDict
    fields = [field for field, value in get_field_details(model).items() if not value['is_relation']]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }

class CurrencyListTable(tables.Table):
  '''Отображает таблицу Валют на странице Валюта'''
  
  name = tables.LinkColumn('currency-update', args=[tables.A('pk')])
  class Meta:
    model = Currency
    fields = [field for field, value in get_field_details(model).items() if not value['is_relation']]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }

class CategoryListTable(tables.Table):
  '''Таблица Категорий отображаемая на странице Производители'''
  # actions = tables.TemplateColumn(
  #   template_name='manufacturer/actions.html',
  #   orderable=False,
  #   verbose_name='Действия',
  #   attrs = {'td': {'class': 'text-right'}}
  # )
  class Meta:
    model = Category
    fields = ['parent', 'name']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
    
