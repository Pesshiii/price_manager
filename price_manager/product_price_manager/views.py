from supplier_product_manager.models import SupplierProduct, SP_PRICES
from supplier_product_manager.tables import SupplierProductPriceManagerTable
# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404,
                              resolve_url)
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
from typing import Optional, Any, Dict, Iterable
from collections import defaultdict, OrderedDict
from django.db.models import (F, ExpressionWrapper, 
                              fields, Func, 
                              Value, Min,
                              Q, DecimalField,
                              OuterRef, Subquery)
from django.db.models.functions import Ceil

from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_htmx.http import HttpResponseClientRefresh 

# Импорты моделей, функций, форм, таблиц
from .models import PriceManager, PriceTag
from supplier_manager.models import Discount, Supplier
from file_manager.models import FileModel
from core.utils import *
from main_product_manager.models import MainProduct, MainProductLog, MP_PRICES, PRICE_TYPES
from .forms import *
from .tables import *
from .filters import *

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math


def _rule_error(cd):
  """Общая проверка формы правила; текст ошибки или None."""
  if cd['price_fixed'] and cd['fixed_price'] == 0:
    return 'Не указана фиксированная цена'
  if not cd['price_fixed']:
    if not cd['source']:
      return 'Поле от какой цены считать должно быть указано'
    if cd['source'] == cd['dest']:
      return 'Поля от какой цены считать и какую цену считать совпадают'
    if (cd['price_from'] and cd['price_to']
      and cd['price_from'] >= cd['price_to']):
      return 'Неверный диапозон цены'
  return None


class RuleFormRefreshMixin:
  """Живая форма правила: смена поставщика, источника или цели шлёт форму
  с ?refresh=1, и она перерисовывается под новые значения — без валидации
  и без сохранения. Проверка идёт первой в post(): save() правила
  пересобирает ценники, до него перерисовка дойти не должна.
  """
  lock_supplier = False

  def is_refresh(self):
    return bool(self.request.GET.get('refresh'))

  def refresh(self):
    initial = self.get_initial()
    initial.update(self.get_form_class().initial_from_data(self.request.POST))
    if self.lock_supplier:
      initial.pop('supplier', None)
    form = self.get_form_class()(initial=initial, instance=self.object,
                                 lock_supplier=self.lock_supplier)
    return self.render_to_response(self.get_context_data(form=form))

  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['lock_supplier'] = self.lock_supplier
    return kwargs

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    form = context['form']
    context['supplier'] = form.rule_supplier
    context['selected_discount_ids'] = form.selected_discount_ids()
    return context

class PriceManagerList(SingleTableView):
  '''Отображение наценок << /supplier/pricemanagers/<int:pk> >>'''
  model = PriceManager
  table_class = PriceManagerListTable
  template_name = 'price_manager/partials/table.html'
  def get(self, request, *args, **kwargs):
    if self.request.htmx:
      self.template_name = 'price_manager/partials/table.html#table'
    return super().get(request, *args, **kwargs)
  def get_queryset(self):
    qs = super().get_queryset()
    pk = self.kwargs.get('pk', None)
    if pk:
      return qs.filter(supplier=pk)
    return qs
  


class PriceManagerCreate(RuleFormRefreshMixin, CreateView):
  '''Создание Наценки <<price-manager/create/>>

  Поставщик выбирается в самой форме. create-for/<pk> и ?supplier=<pk>
  только предвыбирают его; при сохранении решает поле формы, а форма
  всегда шлётся на price-manager/create/.
  '''
  model = PriceManager
  form_class = PriceManagerForm
  template_name = 'price_manager/partials/create.html'
  def get_success_url(self):
    return resolve_url('price-manager')
  def get_initial(self):
    initial = super().get_initial()
    pk = self.kwargs.get('pk') or self.request.GET.get('supplier')
    if pk and str(pk).isdigit():
      initial['supplier'] = get_object_or_404(Supplier, pk=pk).pk
    return initial
  def post(self, request, *args, **kwargs):
    self.object = None
    if self.is_refresh():
      return self.refresh()
    return super().post(request, *args, **kwargs)
  def _format_value(self, value):
    return str(value) if not value is None else '—'
  def _build_generated_name(self, supplier, cleaned_data):
    source = 'fixed_price' if cleaned_data.get('price_fixed') else cleaned_data.get('source')
    has_rrp_value = cleaned_data.get('has_rrp')
    has_rrp_map = {True: 'Да', False: 'Нет', None: 'Без разницы'}
    discounts = cleaned_data.get('discounts')
    discount_value = ','.join(sorted(discounts.values_list('name', flat=True))) if discounts else 'Все'
    dest_label = PRICE_TYPES.get(cleaned_data.get('dest'))
    source_label = PRICE_TYPES.get(source)
    price_range_label = f'{self._format_value(cleaned_data.get("price_from"))}..{self._format_value(cleaned_data.get("price_to"))}'
    if source == 'fixed_price':
      formula_label = f'фикс {self._format_value(cleaned_data.get("fixed_price"))} тг'
    else:
      formula_label = f'+{self._format_value(cleaned_data.get("markup"))}% + {self._format_value(cleaned_data.get("increase"))} тг'
    base_name = ' | '.join([
      f'{supplier.name if supplier else "Без поставщика"}',
      f'{dest_label} ← {source_label}',
      f'РРЦ: {has_rrp_map.get(has_rrp_value)}',
      f'Скидки: {discount_value}',
      f'Диапазон: {price_range_label}',
      f'Расчет: {formula_label}',
    ])
    generated_name = base_name
    suffix = 2
    while PriceManager.objects.filter(name=generated_name).exists():
      generated_name = f'{base_name} ({suffix})'
      suffix += 1
    return generated_name
  def form_invalid(self, form):
    messages.error(self.request, 'Ошибка')
    response = super().form_invalid(form)
    return response
  def form_valid(self, form):
    cd = form.cleaned_data
    supplier = cd['supplier']
    error = _rule_error(cd)
    if error:
      form.add_error(field=None, error=error)
      return self.form_invalid(form)
    instance = form.save(commit=False)
    instance.name = self._build_generated_name(supplier, cd)
    instance.save()
    instance.discounts.set(cd['discounts'])
    messages.success(self.request, 'Менеджер добавлен')
    return HttpResponseClientRefresh()



class PriceManagerUpdate(RuleFormRefreshMixin, SingleTableMixin, UpdateView):
  '''Обновление Наценки <<price-manager/<int:pk>/>>

  Поставщик правила заблокирован — см. PriceManagerForm.
  '''
  model = PriceManager
  form_class = PriceManagerForm
  template_name = 'price_manager/partials/update.html'
  lock_supplier = True
  def get_success_url(self):
    return resolve_url('pricemanager-update', self.kwargs.get('pk', None))
  def get_initial(self):
    initial = super().get_initial()
    initial['price_fixed'] = self.object.source == 'fixed_price'
    return initial
  def post(self, request, *args, **kwargs):
    self.object = self.get_object()
    if self.is_refresh():
      return self.refresh()
    if request.POST.get('delete', None) == 'true':
      self.object.delete()
      return HttpResponseClientRefresh()
    return super().post(request, *args, **kwargs)
  def form_valid(self, form):
    cd = form.cleaned_data
    error = _rule_error(cd)
    if error:
      form.add_error(field=None, error=error)
      return self.form_invalid(form)
    instance = form.save(commit=False)
    instance.save()
    instance.discounts.set(cd['discounts'])
    messages.success(self.request, 'Обновления менеджера сохранены')
    return HttpResponseClientRefresh()
  


class PriceManagerPage(TemplateView):
  """«Наценки ГП»: все правила наценок строк ГП — поставщиков и без поставщика.

  Правила поставщика по-прежнему видны и на его странице; здесь — общий
  список, включая правила без поставщика (на наборы, возвраты, бонусы,
  остатки). ?supplier=none|<pk> — фильтр, ?deprecated=1 — показать
  устаревшие.
  """
  template_name = 'price_manager/page.html'

  def get_context_data(self, **kwargs):
    from django.db.models import Count
    context = super().get_context_data(**kwargs)
    rules = (PriceManager.objects.select_related('supplier')
             .prefetch_related('discounts')
             .annotate(rows_count=Count('pricetags', distinct=True)))
    show_deprecated = self.request.GET.get('deprecated') == '1'
    if not show_deprecated:
      rules = rules.filter(deprecated=False)
    counts = {
      'all': rules.count(),
      'none': rules.filter(supplier__isnull=True).count(),
    }
    selected = self.request.GET.get('supplier', '')
    selected_supplier = None
    if selected == 'none':
      rules = rules.filter(supplier__isnull=True)
    elif selected.isdigit():
      selected_supplier = Supplier.objects.filter(pk=selected).first()
      rules = rules.filter(supplier=selected_supplier)
    context.update({
      'rules': rules.order_by('supplier__name', 'dest', 'source', 'name'),
      'counts': counts,
      'selected': selected,
      'selected_supplier': selected_supplier,
      'show_deprecated': show_deprecated,
      'suppliers': (Supplier.objects.annotate(rules_count=Count('pricemanagers'))
                    .filter(rules_count__gt=0).order_by('name')),
      'price_types': PRICE_TYPES,
    })
    return context


class FixedPriceTagPage(TemplateView):
  """«Фиксированные наценки»: наценки, заданные на самой строке ГП.

  Это PriceTag без правила (p_manager пуст) — их пересчитывает update_prices
  после правил, так что они перекрывают наценки поставщиков. Правятся той же
  модалкой, что и в карточке товара (PriceTagUpdate). Фильтры: ?q= — артикул
  или название строки/товара, ?supplier=none|<pk>, ?dest=<цена>,
  ?deprecated=1 — показать устаревшие.
  """
  template_name = 'price_manager/fixed_pricetags.html'
  paginate_by = 100

  def get_context_data(self, **kwargs):
    from django.core.paginator import Paginator
    context = super().get_context_data(**kwargs)
    params = self.request.GET
    tags = (PriceTag.objects.filter(p_manager__isnull=True)
            .select_related('mp', 'mp__supplier', 'mp__product'))
    show_deprecated = params.get('deprecated') == '1'
    if not show_deprecated:
      tags = tags.filter(deprecated=False)
    q = params.get('q', '').strip()
    if q:
      tags = tags.filter(Q(mp__sku__icontains=q) | Q(mp__article__icontains=q)
                         | Q(mp__name__icontains=q) | Q(mp__product__name__icontains=q))
    counts = {'all': tags.count(), 'none': tags.filter(mp__supplier__isnull=True).count()}
    selected = params.get('supplier', '')
    selected_supplier = None
    if selected == 'none':
      tags = tags.filter(mp__supplier__isnull=True)
    elif selected.isdigit():
      selected_supplier = Supplier.objects.filter(pk=selected).first()
      tags = tags.filter(mp__supplier=selected_supplier)
    dest = params.get('dest', '')
    if dest in MP_PRICES:
      tags = tags.filter(dest=dest)
    else:
      dest = ''
    page = Paginator(tags.order_by('mp__sku', 'mp__supplier__name', 'dest', 'pk'),
                     self.paginate_by).get_page(params.get('page'))
    for tag in page:
      tag.current_price = getattr(tag.mp, tag.dest, None) if tag.dest else None
    query = params.copy()
    query.pop('page', None)
    context.update({
      'page': page,
      'counts': counts,
      'q': q,
      'selected': selected,
      'selected_supplier': selected_supplier,
      'dest': dest,
      'dests': [(field, PRICE_TYPES[field]) for field in MP_PRICES],
      'show_deprecated': show_deprecated,
      'query': query.urlencode(),
      'suppliers': Supplier.objects.filter(
        pk__in=PriceTag.objects.filter(p_manager__isnull=True).values('mp__supplier')).order_by('name'),
    })
    return context


class PriceManagerDetail(DetailView):
  '''Детали Наценки <<price-manager/<int:id>/>>'''
  model = PriceManager
  template_name = 'price_manager/detail.html'
  pk_url_kwarg = 'id'
  context_object_name = 'price_manager'

class PriceManagerDelete(DeleteView):
  model = PriceManager
  template_name = 'price_manager/confirm_delete.html'
  pk_url_kwarg = 'id'
  success_url = '/price-manager/'

class PriceTagList(TemplateView):
  '''Отображение наценок <</price_manager/>>'''
  template_name = 'price_manager/partials/pricetag_list.html'
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['mainproduct'] = MainProduct.objects.get(pk=self.kwargs.get('pk',None))
    pricetags = PriceTag.objects.filter(mp=self.kwargs.get('pk',None))
    # Заданные на самом товаре и пришедшие из менеджеров наценок показываются
    # раздельно: вторые перезаписывает правило, править их надо в менеджере.
    context['fixed_pricetags'] = pricetags.filter(p_manager__isnull=True).order_by('dest')
    context['manager_pricetags'] = (pricetags.filter(p_manager__isnull=False)
                                    .select_related('p_manager').order_by('p_manager__name', 'dest'))
    return context

def _pricetag_error(mp, cd):
  """Почему наценка не подходит строке ГП — или None.

  У строки без поставщика нет прайса поставщика: наценка от его цены считала
  бы от пустого, и clear_unsourced_prices очищал бы её цену при каждом
  пересчёте. Себестоимость строки набора — сумма комплектующих, её наценка не
  пишет (product.services.set_rows).
  """
  if mp.supplier_id is None and not cd['price_fixed'] and cd['source'] in SP_PRICES:
    return 'У строки без поставщика нет прайса поставщика — считайте от цены ГП или задайте фиксированную'
  if mp.is_set and cd['dest'] == 'prime_cost':
    return 'Себестоимость строки набора — сумма себестоимостей комплектующих, наценка её не меняет'
  return None


def _pricetag_form_error(mp, cd):
  """Проверка формы фиксированной наценки: (поле, текст) или None."""
  if cd['price_fixed']:
    if not cd['fixed_price']:
      return 'fixed_price', 'Не указана фиксированная цена'
  else:
    if not cd['source']:
      return 'source', 'Поле от какой цены считать должно быть указано'
    if cd['source'] == cd['dest']:
      return None, 'Поля от какой цены считать и какую цену считать совпадают'
  error = _pricetag_error(mp, cd)
  return (None, error) if error else None


class _PriceTagFormMixin:
  """Модалка фиксированной наценки строки ГП — с карточки товара и со
  страницы «Фиксированные наценки»; успех перезагружает ту, откуда открыли."""
  model = PriceTag
  form_class = PriceTagForm
  template_name = 'price_manager/partials/pricetag_form.html'

  def get_mainproduct(self):
    raise NotImplementedError

  def get_form_kwargs(self):
    # Форма сужает выбор источника и цели под строку (PriceTagForm).
    kwargs = super().get_form_kwargs()
    kwargs['mp'] = self.get_mainproduct()
    return kwargs

  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    context['mainproduct'] = self.get_mainproduct()
    context['action'] = self.request.path
    return context

  def form_invalid(self, form):
    messages.error(self.request, 'Ошибка')
    return super().form_invalid(form)

  def form_valid(self, form):
    cd = form.cleaned_data
    mp = self.get_mainproduct()
    error = _pricetag_form_error(mp, cd)
    if error:
      form.add_error(*error)
      return self.form_invalid(form)
    instance = form.save(commit=False)
    instance.mp = mp
    if cd['price_fixed']:
      instance.source = 'fixed_price'
    instance.save()
    messages.success(self.request, self.success_message)
    return HttpResponseClientRefresh()


class PriceTagCreate(_PriceTagFormMixin, CreateView):
  success_message = 'Наценка добавлена'

  def get_mainproduct(self):
    if not hasattr(self, '_mainproduct'):
      self._mainproduct = get_object_or_404(MainProduct.objects.select_related('supplier'), pk=self.kwargs['pk'])
    return self._mainproduct


class PriceTagUpdate(_PriceTagFormMixin, UpdateView):
  """Правка и удаление (POST delete=true) фиксированной наценки.

  Наценки из правил (p_manager) здесь не правятся — их перезапишет правило.
  """
  success_message = 'Наценка сохранена'

  def get_queryset(self):
    return PriceTag.objects.filter(p_manager__isnull=True).select_related('mp', 'mp__supplier')

  def get_mainproduct(self):
    return self.object.mp

  def get_initial(self):
    initial = super().get_initial()
    initial['price_fixed'] = self.object.is_fixed_price
    return initial

  def post(self, request, *args, **kwargs):
    if request.POST.get('delete') == 'true':
      self.get_object().delete()
      messages.success(request, 'Наценка удалена')
      return HttpResponseClientRefresh()
    return super().post(request, *args, **kwargs)
