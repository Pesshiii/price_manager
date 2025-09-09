from django.utils.html import format_html, mark_safe
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from .functions import *
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
    fields = ['name']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
    
class SettingListTable(tables.Table):
  '''Таблица отображаемая на странице Поставщик/Настройки'''
  actions = tables.TemplateColumn(
    template_name='supplier/setting/actions.html',
    orderable=False,
    verbose_name='Действия',
    attrs = {'td': {'class': 'text-right'}}
  )
  name = tables.LinkColumn('setting-detail', args=[tables.A('pk')])
  class Meta:
    model = Setting
    fields = [field for field in get_field_details(model).keys()]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }

class SupplierProductListTable(tables.Table):
  '''Таблица отображаемая на странице Постащик:имя'''
  actions = tables.TemplateColumn(
    template_name='supplier/product/actions.html',
    orderable=False,
    verbose_name='Действия',
    attrs = {'td': {'class': 'text-right'}}
  )
  class Meta:
    model = SupplierProduct
    fields = SP_TABLE_FIELDS
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
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


class DictFormTable(tables.Table):
  key = tables.TemplateColumn('''{% load special_tags %}{{ record|get:'key' }}''',   verbose_name="Если", orderable=False)
  value  = tables.TemplateColumn('''{% load special_tags %}{{ record|get:'value' }}''',    verbose_name="То", orderable=False)
  DELETE = tables.TemplateColumn('''{% load special_tags %}<button type='submit' class='btn btn-danger' name='delete' value='{{record|get:'btn'}}'><i class="bi bi-x"></i></button>''', verbose_name="", orderable=False)
  class Meta:
    attrs = {"class": "table-auto"}

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

class ManufacturerListTable(tables.Table):
  '''Таблица Производителей отображаемая на странице Производители'''
  # actions = tables.TemplateColumn(
  #   template_name='manufacturer/actions.html',
  #   orderable=False,
  #   verbose_name='Действия',
  #   attrs = {'td': {'class': 'text-right'}}
  # )
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
    

class MainProductListTable(tables.Table):
  '''Таблица Главного прайса отображаемая на главной странице'''
  actions = tables.Column(empty_values=(),
                         orderable=False,
                         verbose_name='')
  def __init__(self, *args, **kwargs):
    self.request = kwargs.pop('request')
    super().__init__(*args, **kwargs)
  
  class Meta:
    model = MainProduct
    fields = ['actions']
    fields.extend(MP_TABLE_FIELDS)
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'clickable-rows table table-auto table-stripped table-hover'
      }
  def render_actions(self, record):
        return render_to_string(
            'main/product/actions.html',
            {
                'record': record,
                'basket': self.request.session.get('basket', []),
            }
        )
  def render_name(self, record):
    return render_to_string(
      'main/product/card.html',
      {
        'record': record,
      }
    )


class SupplierProductPriceManagerTable(tables.Table):
  '''Таблица для сортировки Товаров Поставщиков'''
  class Meta:
    model = SupplierProduct
    fields = SP_TABLE_FIELDS
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
    

class PriceManagerListTable(tables.Table):
  '''Таблица Наценок отображаемая на странице Наценки'''
  name = tables.LinkColumn('price-manager-detail', args=[tables.A('pk')])
  class Meta:
    model = PriceManager
    fields = [key for key, value in get_field_details(PriceManager).items() if not '_ptr' in key]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }