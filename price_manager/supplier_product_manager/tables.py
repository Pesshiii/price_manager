from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from .forms import *

from core.functions import get_field_details

import pandas as pd

class SettingListTable(tables.Table):
  '''Таблица отображаемая на странице Поставщик/Настройки'''
  actions = tables.TemplateColumn(
    template_name='supplier/setting/actions.html',
    orderable=False,
    verbose_name='Действия',
    attrs = {'td': {'class': 'text-right'}}
  )
  name = tables.LinkColumn('upload', args=['setting-update', tables.A('pk')])
  class Meta:
    model = Setting
    fields = [field for field in get_field_details(model).keys()]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }

class SupplierProductListTable(tables.Table):
  '''Таблица отображаемая на странице Постащик:имя'''
  main_basic_price = tables.Column(
    accessor='main_product.basic_price',
    verbose_name='Базовая цена (главный прайс)'
  )
  main_m_price = tables.Column(
    accessor='main_product.m_price',
    verbose_name='Цена ИМ (главный прайс)'
  )
  main_wholesale_price = tables.Column(
    accessor='main_product.wholesale_price',
    verbose_name='Опт (главный прайс)'
  )
  main_wholesale_price_extra = tables.Column(
    accessor='main_product.wholesale_price_extra',
    verbose_name='Опт 1 (главный прайс)'
  )
  actions = tables.TemplateColumn(
    template_name='supplier/product/actions.html',
    orderable=False,
    verbose_name='Действия',
    attrs = {'td': {'class': 'text-right'}}
  )
  def render_main_basic_price(self, value):
    return value if value is not None else '-'
  def render_main_m_price(self, value):
    return value if value is not None else '-'
  def render_main_wholesale_price(self, value):
    return value if value is not None else '-'
  def render_main_wholesale_price_extra(self, value):
    return value if value is not None else '-'
  class Meta:
    model = SupplierProduct
    fields = [
      'discounts',
      'article',
      'name',
      'supplier_price',
      'rrp',
      'main_basic_price',
      'main_m_price',
      'main_wholesale_price',
      'main_wholesale_price_extra',
    ]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows table-sm supplier-products-table'
      }
    
class LinkListTable(tables.Table):
  '''Таблица отображаемая на странице Настройка/Связки'''
  class Meta:
    model = Link
    fields = [field for field in get_field_details(model).keys()]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }


class HTMLColumn(tables.Column):
  def render_header(self, bound_column, **kwargs):
    return mark_safe(str(bound_column.header))

def get_link_create_table():
  class LinkCreateTable(tables.Table):
    """Таблица с выбиралками на хэдэрах для создания Настроек"""
    class Meta:
      template_name = 'django_tables2/bootstrap5.html'
      attrs = {'class': 'table table-auto table-striped table-bordered'}
    def __init__(self, *args, **kwargs):
      # Remove dataframe from kwargs to avoid passing it to parent
      columns = kwargs.pop('columns', None)
      # Initialize columns based on DataFrame columns
      links = kwargs.pop('links', {})
      for i in range(len(columns)):
        if columns[i] in links:
          initial = {'key': links[columns[i]], 'value': columns[i]}
        else:
          initial = {'key':'', 'value':columns[i]}
        self.base_columns[columns[i]] = HTMLColumn(
          verbose_name=format_html('''
              <div class="header-content">
                  <div class="header-title">
                    <span>{}</span>
                    <div class="header-widget">
                        {}
                    </div>
                  </div>
              </div>''', 
              columns[i],
              LinkForm(initial=initial, 
                        prefix=f'link-form-{i}').as_p()),
          orderable=False
        )
      super().__init__(*args, **kwargs)
  return LinkCreateTable


def get_upload_list_table():
  """Предварительное отображение загружаемых данных"""
  class UploadListTable(tables.Table):
    class Meta:
      template_name = 'django_tables2/bootstrap5.html'
      attrs = {'class': 'table table-auto table-striped table-bordered'}
    def __init__(self, *args, **kwargs):
      # Remove dataframe from kwargs to avoid passing it to parent
      links = dict(kwargs.pop('links', None))
      # Initialize columns based on DataFrame columns
      if links is not None:
        for column, field in links.items():
          self.base_columns[column] = tables.Column(verbose_name=f'{column}/{field}')
      super().__init__(*args, **kwargs)
  return UploadListTable



class SupplierProductPriceManagerTable(tables.Table):
  '''Таблица для сортировки Товаров Поставщиков'''
  class Meta:
    model = SupplierProduct
    fields = SP_TABLE_FIELDS
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
    

class DictFormTable(tables.Table):
  key = tables.TemplateColumn('''{% load special_tags %}{{ record|get:'key' }}''',   verbose_name="Если", orderable=False)
  value  = tables.TemplateColumn('''{% load special_tags %}{{ record|get:'value' }}''',    verbose_name="То", orderable=False)
  DELETE = tables.TemplateColumn('''{% load special_tags %}<button type='submit' class='btn btn-danger' name='delete' value='{{record|get:'btn'}}'><i class="bi bi-x"></i></button>''', verbose_name="", orderable=False)
  class Meta:
    attrs = {"class": "table-auto"}
