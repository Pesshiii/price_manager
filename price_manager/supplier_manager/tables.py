from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.template.loader import render_to_string
import django_tables2 as tables
from django.db.models import Q



from .models import *
from core.utils import *
from .forms import *

import pandas as pd

class CurrencyListTable(tables.Table):
  '''Отображает таблицу Валют на странице Валюта'''
  
  name = tables.LinkColumn('currency-update', args=[tables.A('pk')])
  class Meta:
    model = Currency
    fields = [field for field, value in get_field_details(model).items() if not value['is_relation']]
    template_name = 'django_tables2/bootstrap5.html'
    attrs = {
      'class': 'table table-auto table-stripped table-hover clickable-rows'
      }
