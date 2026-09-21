from django.utils.html import format_html
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import F, Case, When, Q, Value
import django_tables2 as tables

from .models import *
from core.utils import *
from .forms import *

import pandas as pd

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
