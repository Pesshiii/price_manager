import django_tables2 as tables

from .models import *
from core.functions import *
from .forms import *


class PriceManagerListTable(tables.Table):
  '''Таблица Наценок отображаемая на странице Наценки'''
  name = tables.LinkColumn('price-manager-update', args=[tables.A('pk')])
  class Meta:
    model = PriceManager
    fields = ['name', 'source', 'dest', 'price_from', 'price_to']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }


class SpecialPriceTable(tables.Table):
  name = tables.LinkColumn('speicalprice-update', args=[tables.A('pk')])
  class Meta:
    model = SpecialPrice
    fields = ['source', 'dest', 'price_type', 'fixed_price']
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }