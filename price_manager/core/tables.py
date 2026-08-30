from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from .utils import *
from .forms import *
from main_product_manager.models import MainProduct

import pandas as pd


class CartItemProductTable(tables.Table):
  '''Таблица Главного прайса для выбора товаров в элемент корзины.

  Каждая строка получает чекбокс для массового добавления, а название товара
  добавляет его в «Подходящие товары» по клику.
  '''
  select = tables.Column(verbose_name='', orderable=False, empty_values=())

  class Meta:
    model = MainProduct
    fields = ['select', 'sku', 'article', 'name', 'supplier', 'manufacturer', 'stock']
    template_name = 'core/includes/table_htmx.html'
    attrs = {
      'class': 'table table-hover table-sm align-middle mb-0'
      }

  def __init__(self, *args, **kwargs):
    self.request = kwargs.pop('request')
    self.url = kwargs.pop('url', None)
    self.item = kwargs.pop('item')
    self.existing_ids = set(kwargs.pop('existing_ids', ()))
    if not self.url:
      self.url = self.request.path_info
    if 'data' in kwargs:
      kwargs['data'] = kwargs['data'].prefetch_related('supplier', 'manufacturer')
    super().__init__(*args, **kwargs)

  def render_select(self, record):
    return render_to_string(
      'shopping_tab/includes/product_select_cell.html',
      {
        'record': record,
        'added': record.pk in self.existing_ids,
      },
    )

  def render_name(self, record):
    return render_to_string(
      'shopping_tab/includes/product_add_name.html',
      {
        'record': record,
        'item': self.item,
      },
    )
