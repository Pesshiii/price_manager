from django.utils.html import format_html
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import F, Case, When, Q, Value
import django_tables2 as tables

from .models import *
from core.utils import *
from .forms import *
from .columns import (
  DEFAULT_VISIBLE_COLUMNS,
  AVAILABLE_COLUMN_GROUPS,
  AVAILABLE_COLUMN_CHOICES,
  AVAILABLE_COLUMN_MAP,
)
from .utils import get_file_url

import pandas as pd

class MainProductTable(tables.Table):
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
  pim_photo = tables.Column(verbose_name='PIM • Фото', orderable=False, empty_values=())
  pim_name = tables.Column(verbose_name='PIM • Название', orderable=False, empty_values=())
  pim_number = tables.Column(verbose_name='PIM • Номер', orderable=False, empty_values=())
  pim_categories = tables.Column(verbose_name='PIM • Категории', orderable=False, empty_values=())
  pim_tags = tables.Column(verbose_name='PIM • Теги', orderable=False, empty_values=())
  pim_brand = tables.Column(verbose_name='PIM • Бренд', orderable=False, empty_values=())
  pim_ean = tables.Column(verbose_name='PIM • EAN', orderable=False, empty_values=())
  pim_status = tables.Column(verbose_name='PIM • Статус', orderable=False, empty_values=())

  def __init__(self, *args, **kwargs):
    self.pim_map = kwargs.pop('pim_map', {})
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
          default='',
        )
      )
      for key, verbose_name in AVAILABLE_COLUMN_CHOICES
      if '__' in key
    ]

    if not self.url:
      self.url = self.request.path_info
    if 'data' in kwargs:
      kwargs['data'] = kwargs['data'].prefetch_related('supplier', 'categories', 'manufacturer')
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
      'name',
      'description',
      'supplier',
      'categories',
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
  def render_stock_msg(self, record):
    if not record.supplier:
      return ''
    if not record.stock or record.stock == 0:
      return record.supplier.msg_navailable
    else:
      return record.supplier.msg_available

  def render_delivery_days(self, record):
    if not record.supplier:
      return ''
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

  def _pim(self, record):
    return self.pim_map.get(record.pk)

  def render_pim_photo(self, record):
    data = self._pim(record)
    if not data:
      return '—'
    image_id = data.get('mainImageId') or data.get('imageId')
    url = get_file_url(image_id)
    if not url:
      return '—'
    return format_html(
      '<img src="{}" style="max-height:50px;max-width:80px;object-fit:contain" loading="lazy" />',
      url,
    )

  def render_pim_name(self, record):
    data = self._pim(record)
    return data.get('name') or '—' if data else '—'

  def render_pim_number(self, record):
    data = self._pim(record)
    return data.get('number') or '—' if data else '—'

  def render_pim_categories(self, record):
    data = self._pim(record)
    if not data:
      return '—'
    cats = data.get('categoriesNames') or {}
    return ', '.join(cats.values()) or '—'

  def render_pim_tags(self, record):
    data = self._pim(record)
    if not data:
      return '—'
    tags = data.get('tag') or []
    return ', '.join(tags) or '—'

  def render_pim_brand(self, record):
    data = self._pim(record)
    return data.get('brandName') or '—' if data else '—'

  def render_pim_ean(self, record):
    data = self._pim(record)
    return data.get('ean') or '—' if data else '—'

  def render_pim_status(self, record):
    data = self._pim(record)
    return data.get('status') or '—' if data else '—'


class MainProductResolveTable(tables.Table):
  class Meta:
    model = MainProduct
    fields = [
      'sku',
      'article',
      'name',
      'supplier'
    ]
    template_name = 'core/includes/table_htmx.html'
    attrs = {
      'class': 'clickable-rows table table-auto table-stripped table-hover'
      }
    
  def __init__(self, *args, **kwargs):
    self.request = kwargs.pop('request')
    self.url = kwargs.pop('url', None)
    if not self.url:
      self.url = self.request.path_info
    super().__init__(*args, **kwargs)

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
  record_type = tables.Column(
    accessor='record_type',
    verbose_name='Тип записи',
  )

  class Meta:
    model = MainProductLog
    fields = ['update_time', 'record_type', 'price_type', 'price', 'stock']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'clickable-rows table table-auto table-striped table-hover align-middle mb-0'
      }
    paginate=False

  def render_update_time(self, value):
    return timezone.localtime(value).strftime('%d.%m.%Y %H:%M')

  def render_record_type(self, value):
    if value == 'price':
      return format_html('<span class="badge text-bg-primary">Тип цены</span>')
    return format_html('<span class="badge text-bg-success">Остаток</span>')

  def render_price_type(self, value):
    if not value:
      return '—'
    return PRICE_TYPES.get(value, value)

  def render_price(self, value):
    if value is None:
      return '—'
    return f'{value:.2f} тг'

  def render_stock(self, value):
    if value is None:
      return '—'
    return f'{value} шт.'
