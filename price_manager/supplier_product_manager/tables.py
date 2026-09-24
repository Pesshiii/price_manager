from datetime import timedelta
from django.utils.html import format_html
from django.utils import timezone
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from .forms import *

from core.utils import get_field_details

import pandas as pd


SP_DEFAULT_VISIBLE_COLUMNS = [
  'actions',
  'article',
  'name',
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
      ('description', 'Описание'),
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
      ('main_product__m_price', 'ГП • Цена ИМ'),
      ('main_product__wholesale_price', 'ГП • Оптовая цена'),
      ('main_product__wholesale_price_extra', 'ГП • Оптовая цена доп.'),
      ('main_product__basic_price', 'ГП • Базовая цена'),
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
  # Annotated by SettingList.get_queryset (last_run_pk/_status/_at).
  last_import = tables.Column(verbose_name='Последний импорт', accessor='last_run_status',
                              empty_values=(), orderable=False)

  class Meta:
    model = Setting
    fields = ['name', 'last_import']
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

  def render_last_import(self, record):
    status = getattr(record, 'last_run_status', None)
    if not status:
      return '—'
    if status == ImportRun.STATUS_NEEDS_CONFIRMATION:
      return format_html("""
        <button type="button" class="btn btn-sm btn-warning"
          data-bs-toggle="modal"
          data-bs-target="#import-confirm-modal"
          hx-get="{}"
          hx-target="#import-confirm-modal .modal-content"
          hx-swap="innerHTML">Ждёт подтверждения</button>
        """, reverse('import-run-confirm', kwargs={'pk': record.last_run_pk}))
    css = {
      ImportRun.STATUS_APPLIED: 'text-success',
      ImportRun.STATUS_REFUSED: 'text-danger',
      ImportRun.STATUS_FAILED: 'text-danger',
    }.get(status, 'text-muted')
    label = dict(ImportRun.STATUS_CHOICES).get(status, status)
    html = format_html('<span class="{}">{}</span> <span class="text-muted small">{}</span>',
                       css, label, timezone.localtime(record.last_run_at).strftime('%d.%m %H:%M'))
    applied_at = getattr(record, 'last_applied_at', None)
    # After a failed or pending run the date above is not when the data last
    # changed; say when it did.
    if status != ImportRun.STATUS_APPLIED:
      html += format_html(' <span class="text-muted small">· данные {}</span>',
                          timezone.localtime(applied_at).strftime('от %d.%m') if applied_at else 'не загружались')
    if setting_overdue(record):
      html += format_html(' <span class="badge text-bg-danger" title="{}">давно не обновлялась</span>',
                          'Последний применённый импорт старше интервала обновления, заданного у поставщика')
    return html
  


def setting_overdue(record, now=None) -> bool:
  """Настройка не обновляла данные дольше интервала, заданного у поставщика.

  Интервал — для того, что настройка грузит: остатка, цен или того и
  другого (берётся меньший). Поставщик целиком этого не покажет: его даты
  обновления двигает любая его настройка, и застывшая вторая настройка
  прячется за работающей первой. Нужны аннотации SettingList.get_queryset.
  """
  supplier = record.supplier
  intervals = [days for maps, days in (
    (getattr(record, 'maps_stock', False), supplier.stock_update_days),
    (getattr(record, 'maps_prices', False), supplier.price_update_days),
  ) if maps and days]
  if not intervals:
    return False
  applied_at = getattr(record, 'last_applied_at', None)
  if applied_at is None:
    return True
  return (now or timezone.now()) - applied_at >= timedelta(days=min(intervals))


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
      'description',
      'discount',
      'stock',
      'supplier_price',
      'rrp',
      'discount_price',
      'updated_at',
    ]
    template_name = 'core/includes/table_scrollbartop.html'
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
