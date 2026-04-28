from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import F, Case, When, Q, Value
import django_tables2 as tables

from .models import *
from core.functions import *
from core.tables import HTMXMixin, SelectableColumnsMixin
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
      ('description', 'Описание'),
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
      ('supplier_product_price', 'Цена поставщика'),
      ('supplier_product_rrp', 'РРЦ'),
      ('supplier_product_discount_price', 'Цена поставщика со скидкой'),
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


class MainProductTable(SelectableColumnsMixin, HTMXMixin, tables.Table):
    '''Таблица Главного прайса отображаемая на главной странице'''
    actions = tables.Column(empty_values=(),
                            orderable=False,
                            verbose_name='')
    stock_msg = tables.Column(verbose_name='Статус наличия',
                                orderable=False,
                                empty_values=())
    supplier_product_price = tables.Column(verbose_name='Цена поставщика', default='—')
    supplier_product_rrp = tables.Column(verbose_name='РРЦ', default='—')
    supplier_product_discount_price = tables.Column(verbose_name='Цена поставщика со скидкой', default='—')
    delivery_days = tables.Column(
        verbose_name='Срок поставки (Рабочие дни)',
        orderable=False,
        empty_values=(),
    )

    class Meta:
        model = MainProduct
        fields = [
        'actions',
        'sku',
        'article',
        'name',
        'description',
        'supplier',
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
        'supplier_product_price',
        'supplier_product_rrp',
        'supplier_product_discount_price',
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
    

    def __init__(self,*args, **kwargs):
        super().__init__(*args, default_columns=DEFAULT_VISIBLE_COLUMNS, column_choices=AVAILABLE_COLUMN_CHOICES, **kwargs)

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

class MainProductResolveTable(HTMXMixin, tables.Table):
  class Meta:
    model = MainProduct
    fields = [
      'sku',
      'article',
      'name',
      'supplier'
    ]
    attrs = {
      'class': 'clickable-rows table table-auto table-stripped table-hover'
      }
    

class CategoryListTable(tables.Table):
  '''Таблица Категорий отображаемая на странице Производители'''
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
