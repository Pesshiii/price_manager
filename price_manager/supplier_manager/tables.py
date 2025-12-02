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
  name = tables.LinkColumn('supplier-detail', args=[tables.A('pk')])
  class Meta:
    model = Supplier
    fields = ['name', 'price_updated_at', 'stock_updated_at']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
  def render_name(self, record):
    now = timezone.now()
    try:
      danger = (now - record.stock_updated_at).days >= TIME_FREQ[record.stock_update_rate] or (now - record.price_updated_at).days >= TIME_FREQ[record.price_update_rate]
    except:
      danger = False
    color = 'danger' if danger else 'success'
    return format_html(f'''<span class=" status-indicator bg-{color} rounded-circle"></span> {record.name}''')
  

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
    
