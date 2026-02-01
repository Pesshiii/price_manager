from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from core.functions import *
from .forms import *

import pandas as pd

class MainProductListTable(tables.Table):
  '''Таблица Главного прайса отображаемая на главной странице'''
  actions = tables.Column(empty_values=(),
                         orderable=False,
                         verbose_name='',
                         attrs={'td': {'data-col': 'actions'}, 'th': {'data-col': 'actions'}})
  sku = tables.Column(
    attrs={'td': {'data-col': 'sku'}, 'th': {'data-col': 'sku'}}
  )
  article = tables.Column(
    attrs={'td': {'data-col': 'article'}, 'th': {'data-col': 'article'}}
  )
  supplier = tables.Column(
    attrs={'td': {'data-col': 'supplier'}, 'th': {'data-col': 'supplier'}}
  )
  name = tables.Column(
    attrs={'td': {'data-col': 'name'}, 'th': {'data-col': 'name'}}
  )
  category = tables.Column(
    attrs={'td': {'data-col': 'category'}, 'th': {'data-col': 'category'}}
  )
  manufacturer = tables.Column(
    attrs={'td': {'data-col': 'manufacturer'}, 'th': {'data-col': 'manufacturer'}}
  )
  stock = tables.Column(
    attrs={'td': {'data-col': 'stock'}, 'th': {'data-col': 'stock'}}
  )
  weight = tables.Column(
    attrs={'td': {'data-col': 'weight'}, 'th': {'data-col': 'weight'}}
  )
  prime_cost = tables.Column(
    attrs={'td': {'data-col': 'prime_cost'}, 'th': {'data-col': 'prime_cost'}}
  )
  wholesale_price = tables.Column(
    attrs={'td': {'data-col': 'wholesale_price'}, 'th': {'data-col': 'wholesale_price'}}
  )
  basic_price = tables.Column(
    attrs={'td': {'data-col': 'basic_price'}, 'th': {'data-col': 'basic_price'}}
  )
  m_price = tables.Column(
    attrs={'td': {'data-col': 'm_price'}, 'th': {'data-col': 'm_price'}}
  )
  wholesale_price_extra = tables.Column(
    attrs={'td': {'data-col': 'wholesale_price_extra'}, 'th': {'data-col': 'wholesale_price_extra'}}
  )
  length = tables.Column(
    attrs={'td': {'data-col': 'length'}, 'th': {'data-col': 'length'}}
  )
  width = tables.Column(
    attrs={'td': {'data-col': 'width'}, 'th': {'data-col': 'width'}}
  )
  depth = tables.Column(
    attrs={'td': {'data-col': 'depth'}, 'th': {'data-col': 'depth'}}
  )
  price_updated_at = tables.Column(
    attrs={'td': {'data-col': 'price_updated_at'}, 'th': {'data-col': 'price_updated_at'}}
  )
  stock_updated_at = tables.Column(
    attrs={'td': {'data-col': 'stock_updated_at'}, 'th': {'data-col': 'stock_updated_at'}}
  )
  price_managers = tables.Column(
    verbose_name='Наценки',
    attrs={'td': {'data-col': 'price_managers'}, 'th': {'data-col': 'price_managers'}}
  )
  special_prices = tables.Column(
    verbose_name='Спец наценки',
    attrs={'td': {'data-col': 'special_prices'}, 'th': {'data-col': 'special_prices'}}
  )
  supplier_delivery_days = tables.Column(
    accessor='supplier.delivery_days',
    verbose_name='Срок поставки (дней)',
    attrs={'td': {'data-col': 'supplier_delivery_days'}, 'th': {'data-col': 'supplier_delivery_days'}}
  )
  supplier_price_update_rate = tables.Column(
    accessor='supplier.price_update_rate',
    verbose_name='Частота обновления цен (поставщик)',
    attrs={'td': {'data-col': 'supplier_price_update_rate'}, 'th': {'data-col': 'supplier_price_update_rate'}}
  )
  supplier_stock_update_rate = tables.Column(
    accessor='supplier.stock_update_rate',
    verbose_name='Частота обновления остатков (поставщик)',
    attrs={'td': {'data-col': 'supplier_stock_update_rate'}, 'th': {'data-col': 'supplier_stock_update_rate'}}
  )
  supplier_currency = tables.Column(
    accessor='supplier.currency',
    verbose_name='Валюта поставщика',
    attrs={'td': {'data-col': 'supplier_currency'}, 'th': {'data-col': 'supplier_currency'}}
  )
  supplier_price_updated_at = tables.Column(
    accessor='supplier.price_updated_at',
    verbose_name='Обновление цены поставщика',
    attrs={'td': {'data-col': 'supplier_price_updated_at'}, 'th': {'data-col': 'supplier_price_updated_at'}}
  )
  supplier_stock_updated_at = tables.Column(
    accessor='supplier.stock_updated_at',
    verbose_name='Обновление остатков поставщика',
    attrs={'td': {'data-col': 'supplier_stock_updated_at'}, 'th': {'data-col': 'supplier_stock_updated_at'}}
  )
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
                'request': self.request,
            },
            request=self.request,
        )
  def render_name(self, record):
    return render_to_string(
      'mainproduct/includes/name.html',
      {
        'record': record,
      }
    )
  def render_price_managers(self, record):
    managers = list(record.price_managers.values_list('name', flat=True))
    return ', '.join(managers) if managers else '-'
  def render_special_prices(self, record):
    specials = [str(item) for item in record.special_prices.all()]
    return ', '.join(specials) if specials else '-'


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
    

class MainProductLogTable(tables.Table):
  class Meta:
    model = MainProductLog
    fields = ['update_time', 'stock', 'price_type', 'price']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'clickable-rows table table-auto table-stripped table-hover'
      }
    paginate=False
