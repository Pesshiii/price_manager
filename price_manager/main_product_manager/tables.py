from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import F, Case, When, Q, Value
import django_tables2 as tables

from .models import *
from core.functions import *
from .forms import *

import pandas as pd

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
    if not self.url:
      self.url = self.request.path_info
    if hasattr(kwargs, 'data'):
      kwargs['data'] = kwargs['data'].prefetch_related('supplier', 'category', 'manufacturer')
    super().__init__(*args, **kwargs)

  class Meta:
    model = MainProduct
    fields = [
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
