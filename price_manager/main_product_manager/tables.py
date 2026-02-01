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
  article = tables.Column(
    attrs={'td': {'data-col': 'article'}, 'th': {'data-col': 'article'}}
  )
  supplier = tables.Column(
    attrs={'td': {'data-col': 'supplier'}, 'th': {'data-col': 'supplier'}}
  )
  name = tables.Column(
    attrs={'td': {'data-col': 'name'}, 'th': {'data-col': 'name'}}
  )
  manufacturer = tables.Column(
    attrs={'td': {'data-col': 'manufacturer'}, 'th': {'data-col': 'manufacturer'}}
  )
  prime_cost = tables.Column(
    attrs={'td': {'data-col': 'prime_cost'}, 'th': {'data-col': 'prime_cost'}}
  )
  stock = tables.Column(
    attrs={'td': {'data-col': 'stock'}, 'th': {'data-col': 'stock'}}
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
