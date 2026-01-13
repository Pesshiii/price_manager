from django.utils.html import format_html
from django.urls import reverse


import django_tables2 as tables

from .models import *
from core.functions import *
from .forms import *


class PriceManagerListTable(tables.Table):
  value = tables.Column(verbose_name='Ценовая зона', empty_values=())
  range = tables.Column(verbose_name='Итоговая цена', empty_values=())
  class Meta:
    model = PriceManager
    fields = ['name', 'source', 'dest', 'has_rrp', 'range', 'value']
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
      """, reverse('pricemanager-update', kwargs={'pk':record.pk}), record.name)
  def render_value(self, record):
    if record.source == 'fixed_price':
      return f'{record.fixed_price} тг'
    if record.increase == 0:
      return f'{(1+record.markup/100)*100}%'
    return f'{(1+record.markup/100)*100}% + {record.increase}'
  def render_range(self, record):
    if record.source == 'fixed_price':
      return "Фиксированная цена"
    res = ''
    if record.price_from:
      res += f'{record.price_from} < '
    res += 'Цена'
    if record.price_to:
      res += f' < {record.price_to}'
    return res


class SpecialPriceTable(tables.Table):
  name = tables.LinkColumn('speicalprice-update', args=[tables.A('pk')])
  class Meta:
    model = SpecialPrice
    fields = ['source', 'dest', 'price_type', 'fixed_price']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }