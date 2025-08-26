from django.utils.html import format_html
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from .functions import *

import pandas as pd

class SupplierListTable(tables.Table):
  '''Таблица отображаемая на странице Поставщики'''
  actions = tables.TemplateColumn(
    template_name='supplier/actions.html',
    orderable=False,
    verbose_name='Действия',
    attrs = {'td': {'class': 'text-left'}}
  )
  name = tables.LinkColumn('supplier-detail', args=[tables.A('pk')])
  class Meta:
    model = Supplier
    fields = [field for field, value in get_field_details(model).items() if not value['type'] == 'ForeignKey']
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
    fields = SP_FIELDS
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

def get_link_create_table():
  class LinkCreateTable(tables.Table):
    """Таблица с выбиралками на хэдэрах для создания Настроек"""
    class Meta:
      template_name = 'includes/table.html'
      attrs = {'class': 'table table-auto table-striped table-bordered'}
    def __init__(self, *args, **kwargs):
      # Remove dataframe from kwargs to avoid passing it to parent
      df = kwargs.pop('df', None)
      widgets = kwargs.pop('widgets', None)
      # Initialize columns based on DataFrame columns
      if df is not None:
        for i in range(len(df.columns)):
          self.base_columns[df.columns[i]] = tables.Column(attrs={
            'th':
              {'widget':widgets[i]}
          })
      super().__init__(*args, **kwargs)
  return LinkCreateTable


class DictFormTable(tables.Table):
    # Each record is a Form; we render its fields right in the cells
    key = tables.TemplateColumn('{{ record.key }}',   verbose_name="Если", orderable=False)
    value  = tables.TemplateColumn('{{ record.value }}',    verbose_name="То", orderable=False)
    DELETE = tables.TemplateColumn('{{ record.enable }}', verbose_name="", orderable=False)
    class Meta:
        attrs = {"class": "table", "id": "items-table"}

def get_upload_list_table():
  """Предварительное отображение загружаемых данных"""
  class UploadListTable(tables.Table):
    class Meta:
      template_name = 'django_tables2/bootstrap5.html'
      attrs = {'class': 'table table-auto table-striped table-bordered'}
    def __init__(self, *args, **kwargs):
      # Remove dataframe from kwargs to avoid passing it to parent
      mapping = dict(kwargs.pop('mapping', None))
      # Initialize columns based on DataFrame columns
      if mapping is not None:
        for key, value in mapping.items():
          self.base_columns[value] = tables.Column(verbose_name=f'{key}/{value}')
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
    fields.extend(MP_FIELDS)
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


class SortSupplierProductTable(tables.Table):
  '''Таблица для сортировки Товаров Поставщиков'''
  selection = tables.CheckBoxColumn(
                accessor='pk',
                attrs={
                  'th__input': {'id': 'selection'},
                  'td__input': {'class': 'select-row'},
                },
                orderable=False
              )
  class Meta:
    model = SupplierProduct
    fields = ['main_product']
    fields.extend([key for key, value in get_field_details(SupplierProduct).items() 
              if not value['primary_key']
              and not key == 'main_product'])
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
  def render_selection(self, value):
      return format_html('<input type="checkbox" name="selected_items" value="{}" />', value)


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
  actions = tables.TemplateColumn(
    template_name='price_manager/actions.html',
    orderable=False,
    verbose_name=format_html(
            '''<button class="btn btn-sm btn-primary" onclick="window.location.href='/price-manager/apply-all'">Применить все</button>'''
        ),
    attrs = {'td': {'class': 'text-right'}}
  )
  name = tables.LinkColumn('price-manager-detail', args=[tables.A('pk')])
  class Meta:
    model = PriceManager
    fields = [key for key, value in get_field_details(PriceManager).items() if not '_ptr' in key]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }