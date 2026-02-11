from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from .forms import *

from core.functions import get_field_details

import pandas as pd


SP_DEFAULT_VISIBLE_COLUMNS = [
  'actions',
  'article',
  'name',
  'manufacturer',
  'supplier_price',
  'rrp',
  'discount',
]


SP_AVAILABLE_COLUMN_GROUPS = [
  (
    'Прайс поставщика',
    [
      ('actions', 'Действия'),
      ('article', 'Артикул поставщика'),
      ('name', 'Название'),
      ('manufacturer', 'Производитель'),
      ('discount', 'Группа скидок'),
      ('stock', 'Остаток'),
      ('supplier_price', 'Цена поставщика'),
      ('rrp', 'РРЦ'),
      ('discount_price', 'Цена со скидкой'),
      ('updated_at', 'Последнее обновление'),
    ],
  ),
  (
    'Связь с главным прайсом',
    [
      ('main_product__sku', 'ГП • SKU'),
      ('main_product__article', 'ГП • Артикул поставщика'),
      ('main_product__name', 'ГП • Название'),
      ('main_product__prime_cost', 'ГП • Себестоимость'),
      ('main_product__stock', 'ГП • Остаток'),
    ],
  ),
  (
    'Поставщик',
    [
      ('supplier__name', 'Поставщик • Название'),
      ('supplier__currency__name', 'Поставщик • Валюта'),
      ('supplier__price_updated_at', 'Поставщик • Обновление цены'),
      ('supplier__stock_updated_at', 'Поставщик • Обновление остатков'),
    ],
  ),
]

SP_AVAILABLE_COLUMN_CHOICES = [item for _, options in SP_AVAILABLE_COLUMN_GROUPS for item in options]
SP_AVAILABLE_COLUMN_MAP = dict(SP_AVAILABLE_COLUMN_CHOICES)

class SettingListTable(tables.Table):
  class Meta:
    model = Setting
    fields = ['name']
    template_name = 'core/includes/table_htmx.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
  def render_name(self, record):
    return format_html("""
      <a
        title="Обновить"
        class="btn btn-sm btn-primary"
        data-bs-toggle="modal"
        data-bs-target="#modal-container"
        hx-get="{}"
        hx-target="#modal-container .modal-content"
        hx-swap="innerHTML">
        <i class="bi bi-pencil-square"></i>
      </a>
        <span>{}</span>
      """, reverse('setting-update', kwargs={'pk':record.pk}), record.name)
  


class SupplierProductListTable(tables.Table):
  '''Таблица отображаемая на странице Постащик:имя'''
  actions = tables.TemplateColumn(
    template_name='supplier/product/actions.html',
    orderable=False,
    verbose_name='Действия',
    attrs = {'td': {'class': 'text-right'}}
  )
  def __init__(self, *args, **kwargs):
    selected_columns = kwargs.pop('selected_columns', None) or []
    if not selected_columns:
      selected_columns = SP_DEFAULT_VISIBLE_COLUMNS
    self.selected_columns = [column for column in selected_columns if column in SP_AVAILABLE_COLUMN_MAP]
    if not self.selected_columns:
      self.selected_columns = SP_DEFAULT_VISIBLE_COLUMNS

    extra_columns = [
      (
        key,
        tables.Column(
          accessor=key,
          verbose_name=verbose_name,
          default='—',
        )
      )
      for key, verbose_name in SP_AVAILABLE_COLUMN_CHOICES
      if '__' in key
    ]
    super().__init__(*args, extra_columns=extra_columns, **kwargs)

    for column_key in SP_AVAILABLE_COLUMN_MAP:
      if column_key not in self.selected_columns and column_key in self.columns:
        self.columns.hide(column_key)

    sequence = [column for column in self.selected_columns if column in self.columns]
    sequence.append('...')
    self.sequence = sequence

  class Meta:
    model = SupplierProduct
    fields = [
      'actions',
      'article',
      'name',
      'manufacturer',
      'discount',
      'stock',
      'supplier_price',
      'rrp',
      'discount_price',
      'updated_at',
    ]
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
