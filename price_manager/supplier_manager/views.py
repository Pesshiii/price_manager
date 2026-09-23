from supplier_product_manager.models import SupplierProduct, SP_PRICES
from supplier_product_manager.tables import SupplierProductPriceManagerTable
# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404)
from django.core.paginator import Paginator
from django.utils import timezone
from django.template.loader import render_to_string
from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import (View,
                                  ListView,
                                  DetailView,
                                  CreateView,
                                  UpdateView,
                                  DeleteView,
                                  FormView,
                                  TemplateView)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.http import Http404
from django.db import IntegrityError
from django.forms import modelform_factory
from typing import Optional, Any, Dict, Iterable
from collections import defaultdict, OrderedDict
from datetime import datetime, timezone as dt_timezone
from django.db.models import Count, Prefetch
from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django.db.models import Q, F, ExpressionWrapper, BooleanField, DurationField, Value, Case, When
from django.db.models.functions import Greatest, ExtractDay


from dal import autocomplete
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh, retarget

# Импорты моделей, функций, форм, таблиц
from .models import *
from file_manager.models import FileModel
from core.utils import *
from main_product_manager.models import MainProduct, MP_PRICES
from .forms import *
from .tables import *

PRICE_COLUMNS = [
  ('basic_price', 'Базовая цена'),
  ('prime_cost', 'Себестоимость'),
  ('m_price', 'Цена ИМ'),
  ('wholesale_price', 'Оптовая цена'),
]

UPDATE_KINDS = [('price', 'Цены'), ('stock', 'Остатки')]


def _status_title(supplier, kind, status):
  if status == 'untracked':
    return 'Интервал обновления не задан'
  interval = format_interval(getattr(supplier, f'{kind}_update_days'))
  if status == 'never':
    return f'Не обновлялось · интервал {interval}'
  updated_at = timezone.localtime(getattr(supplier, f'{kind}_updated_at'))
  return f'Обновлено {updated_at:%d.%m.%Y %H:%M} · интервал {interval}'


class SupplierList(TemplateView):
  '''Список поставщиков на <<supplier/>>'''
  template_name = 'supplier/list.html'

  SORT_FIELDS = {'name', 'total', *PRIORITY_FIELDS, *(key for key, _ in PRICE_COLUMNS)}

  def get_context_data(self, **kwargs) -> dict[str, Any]:
    now = timezone.now()
    context = super().get_context_data(**kwargs)
    sort_by = self.request.GET.get('sort', 'name')
    direction = self.request.GET.get('dir', 'asc')

    if sort_by not in self.SORT_FIELDS:
      sort_by = 'name'
    if direction not in {'asc', 'desc'}:
      direction = 'asc'

    # Все счётчики — одним запросом, а не пятью на каждого поставщика.
    missing = {
      f'{key}_missing': Count(
        'main_products',
        filter=Q(**{f'main_products__{key}__isnull': True}) | Q(**{f'main_products__{key}': 0}),
      )
      for key, _ in PRICE_COLUMNS
    }
    queryset = Supplier.objects.annotate(total=Count('main_products'), **missing)

    def get_row(obj):
      statuses = []
      for kind, label in UPDATE_KINDS:
        status = obj.update_status(kind, now=now)
        statuses.append({'label': label, 'status': status, 'title': _status_title(obj, kind, status)})
      prices = []
      for key, label in PRICE_COLUMNS:
        n_missing = getattr(obj, f'{key}_missing')
        prices.append({
          'key': key,
          'missing': n_missing,
          'coverage': round(100 * (obj.total - n_missing) / obj.total) if obj.total else 0,
        })
      return {
        'pk': obj.pk,
        'name': obj.name,
        'total': obj.total,
        'statuses': statuses,
        'price_priority': obj.price_priority,
        'stock_priority': obj.stock_priority,
        'prices': prices,
        **{key: getattr(obj, f'{key}_missing') for key, _ in PRICE_COLUMNS},
      }

    suppliers = [get_row(obj) for obj in queryset]

    def sort_value(row):
      value = row[sort_by]
      return value.lower() if isinstance(value, str) else value

    reverse = direction == 'desc'
    if sort_by in PRIORITY_FIELDS:
      # Непроранжированные — в конце при любом направлении.
      ranked = sorted((r for r in suppliers if r[sort_by] is not None), key=sort_value, reverse=reverse)
      suppliers = ranked + [r for r in suppliers if r[sort_by] is None]
    else:
      suppliers.sort(key=sort_value, reverse=reverse)

    context["suppliers"] = suppliers
    context["price_columns"] = PRICE_COLUMNS
    context["sort_by"] = sort_by
    context["sort_dir"] = direction
    return context


class SupplierPriorityUpdate(View):
  '''Правка приоритета прямо в ячейке таблицы поставщиков.

  Отвечает той же ячейкой (hx-swap outerHTML) — страница не перезагружается.
  Если занятый номер сдвинул других поставщиков (Supplier.make_room), их
  ячейки приезжают в том же ответе через hx-swap-oob.
  '''
  def post(self, request, pk, field):
    if field not in PRIORITY_FIELDS:
      raise Http404
    supplier = get_object_or_404(Supplier, pk=pk)
    raw = request.POST.get('value', '').strip()
    form = modelform_factory(Supplier, fields=[field])({field: raw}, instance=supplier)
    saved = form.is_valid()
    errors = None if saved else form.errors.get(field)
    shifted = []
    if saved:
      try:
        form.save()
      except IntegrityError:
        # Кто-то занял номер в ряду между make_room и коммитом.
        saved = False
        errors = ['Приоритеты только что изменил кто-то ещё — обновите страницу.']
      else:
        shifted = (
          Supplier.objects.filter(pk__in=supplier.shifted.get(field, []))
          .values_list('pk', field)
        )
    return render(request, 'supplier/partials/priority_response.html', {
      'pk': supplier.pk,
      'field': field,
      'value': getattr(supplier, field) if saved else raw,
      'errors': errors,
      'saved': saved,
      'shifted': shifted,
    })



class SupplierCreate(CreateView):
  '''Таблица создания Поставщиков <<supplier/create/>>'''
  model = Supplier
  form_class=SupplierForm
  success_url = '/supplier'
  template_name = 'supplier/partials/create.html'
  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['url'] = reverse('supplier-create')
    return kwargs
  def form_valid(self, form):
    response = super().form_valid(form)
    return HttpResponseClientRedirect(reverse('supplier'))
  


class SupplierDelete(DeleteView):
  model = Supplier
  success_url = '/supplier/'
  pk_url_kwarg = 'id'
  template_name = 'supplier/confirm_delete.html'

class SupplierUpdate(UpdateView):
  '''Таблица  обновления Поставщиков <<supplier/update/>>'''
  model = Supplier
  form_class = SupplierForm
  template_name = 'supplier/partials/update.html'
  pk_url_kwarg='pk'
  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['url'] = reverse('supplier-update', kwargs={'pk':self.kwargs.get('pk')})
    return kwargs
  def get_template_names(self) -> list[str]:
      if self.request.htmx:
          return [self.template_name+"#form_partial"]
      return super().get_template_names()
  def get_success_url(self):
    return reverse('supplier-update', kwargs={'pk':self.kwargs.get('pk')})
  
  def form_valid(self, form):
    messages.success(self.request, 'Настройки поставщика сохранены.')
    return super().form_valid(form)
  

class CurrencyList(SingleTableView):
  '''Отображает валюты <</currency/>>'''
  model = Currency
  table_class=CurrencyListTable
  template_name = 'currency/list.html'
  def get_table_data(self):
    return Currency.objects.exclude(name='KZT')

class CurrencyCreate(CreateView):
  model = Currency
  fields = '__all__'
  template_name = 'currency/create.html'
  def get_success_url(self):
    return '/currency/'

class CurrencyUpdate(UpdateView):
  model = Currency
  fields = '__all__'
  template_name = 'currency/update.html'
  pk_url_kwarg = 'id'
  def get_success_url(self):
    return '/currency/'
