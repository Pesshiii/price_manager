from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import F, Case, When, Q, Value
import django_tables2 as tables

from .models import *
from core.functions import *
from .forms import *

import pandas as pd


DEFAULT_VISIBLE_COLUMNS = [
  'actions',
  'article',
  'supplier',
  'name',
  'manufacturer',
  'prime_cost',
  'stock',
  'delivery_days',
  'stock_msg',
]


AVAILABLE_COLUMN_GROUPS = [
  (
    'Главный прайс',
    [
      ('actions', 'Действия'),
      ('sku', 'Артикул товара'),
      ('article', 'Артикул поставщика'),
      ('name', 'Название'),
      ('supplier', 'Поставщик'),
      ('manufacturer', 'Производитель'),
      ('category', 'Категория'),
      ('stock', 'Остаток'),
      ('stock_msg', 'Статус наличия'),
      ('delivery_days', 'Срок поставки (Рабочие дни)'),
      ('prime_cost', 'Себестоимость'),
      ('wholesale_price', 'Оптовая цена'),
      ('basic_price', 'Базовая цена'),
      ('m_price', 'Цена ИМ'),
      ('wholesale_price_extra', 'Оптовая цена доп.'),
      ('discount_price', 'Цена со скидкой'),
      ('weight', 'Вес'),
      ('length', 'Длина'),
      ('width', 'Ширина'),
      ('depth', 'Глубина'),
      ('price_updated_at', 'Последнее обновление цены'),
      ('stock_updated_at', 'Последнее обновление остатка'),
    ],
  ),
  (
    'Поставщик',
    [
      ('supplier__name', 'Поставщик • Название'),
      ('supplier__currency__name', 'Поставщик • Валюта'),
      ('supplier__price_updated_at', 'Поставщик • Обновление цены'),
      ('supplier__stock_updated_at', 'Поставщик • Обновление остатков'),
      ('supplier__delivery_days', 'Поставщик • Срок доставки'),
      ('supplier__delivery_days_available', 'Поставщик • Срок поставки при наличии'),
      ('supplier__delivery_days_navailable', 'Поставщик • Срок поставки при отсутствии'),
      ('supplier__price_update_rate', 'Поставщик • Частота обновления цен'),
      ('supplier__stock_update_rate', 'Поставщик • Частота обновления остатков'),
      ('supplier__msg_available', 'Поставщик • Сообщение при наличии'),
      ('supplier__msg_navailable', 'Поставщик • Сообщение при отсутствии'),
    ],
  ),
  (
    'Производитель и категория',
    [
      ('manufacturer__name', 'Производитель • Название'),
      ('category__name', 'Категория • Название'),
      ('category__parent__name', 'Категория • Родитель'),
    ],
  ),
]

AVAILABLE_COLUMN_CHOICES = [item for _, options in AVAILABLE_COLUMN_GROUPS for item in options]
AVAILABLE_COLUMN_MAP = dict(AVAILABLE_COLUMN_CHOICES)

class MainProductTable(tables.Table):
  '''Таблица Главного прайса отображаемая на главной странице'''
  actions = tables.Column(empty_values=(),
                         orderable=False,
                         verbose_name='')
  stock_msg = tables.Column(verbose_name='Статус наличия',
                            orderable=False,
                            empty_values=())
  delivery_days = tables.Column(
    verbose_name='Срок поставки (Рабочие дни)',
    orderable=False,
    empty_values=(),
  )
  def __init__(self, *args, **kwargs):
    self.request = kwargs.pop('request')
    self.url = kwargs.pop('url', None)
    selected_columns = kwargs.pop('selected_columns', None) or []
    if not selected_columns:
      selected_columns = DEFAULT_VISIBLE_COLUMNS
    self.selected_columns = [column for column in selected_columns if column in AVAILABLE_COLUMN_MAP]
    if not self.selected_columns:
      self.selected_columns = DEFAULT_VISIBLE_COLUMNS

    extra_columns = [
      (
        key,
        tables.Column(
          accessor=key,
          verbose_name=verbose_name,
          default='—',
        )
      )
      for key, verbose_name in AVAILABLE_COLUMN_CHOICES
      if '__' in key
    ]

    if not self.url:
      self.url = self.request.path_info
    if 'data' in kwargs:
      kwargs['data'] = kwargs['data'].prefetch_related('supplier', 'category', 'manufacturer')
    super().__init__(*args, extra_columns=extra_columns, **kwargs)

    for column_key in AVAILABLE_COLUMN_MAP:
      if column_key not in self.selected_columns and column_key in self.columns:
        self.columns.hide(column_key)

    sequence = [column for column in self.selected_columns if column in self.columns]
    sequence.append('...')
    self.sequence = sequence

  class Meta:
    model = MainProduct
    fields = [
      'actions',
      'sku',
      'article',
      'supplier',
      'name',
      'category',
      'manufacturer',
      'weight',
      'length',
      'width',
      'depth',
      'prime_cost',
      'wholesale_price',
      'basic_price',
      'm_price',
      'wholesale_price_extra',
      'discount_price',
      'stock',
      'price_updated_at',
      'stock_updated_at',
      'delivery_days',
      'stock_msg',
    ]
    template_name = 'core/includes/table_htmx.html'
    attrs = {
      'class': 'clickable-rows table table-auto table-stripped table-hover'
      }
  def render_stock_msg(self, record):
    if not record.stock or record.stock == 0:
      return record.supplier.msg_navailable
    else:
      return record.supplier.msg_available
  
  def render_delivery_days(self, record):
    return record.supplier.get_delivery_days_for_stock(record.stock)
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
