from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
import django_tables2 as tables

from .models import *
from .forms import *

from core.functions import get_field_details

import pandas as pd

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
  class Meta:
    model = SupplierProduct
    fields = SP_TABLE_FIELDS
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
