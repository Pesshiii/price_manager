# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404)
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
                                  FormView)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse, reverse_lazy
from typing import Optional, Any, Dict, Iterable
from collections import defaultdict, OrderedDict
from django.utils.functional import cached_property
from django.db.models import Prefetch, Q, Value, Max, Subquery, OuterRef, IntegerField, ExpressionWrapper, Case, When
from django.db import transaction
from django.conf import settings
from django.contrib.postgres.search import SearchVector
# Импорты из сторонних приложений
from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView, FilterMixin
from django.core.paginator import Paginator
from django.http import HttpResponse
from decimal import Decimal, InvalidOperation

from dal import autocomplete
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh, retarget
from django.template.context_processors import csrf
from crispy_forms.utils import render_crispy_form


# Импорты моделей, функций, форм, таблиц
from .models import *
from supplier_product_manager.models import SupplierProduct
from file_manager.models import FileModel
from core.utils import *
from .forms import *
from .tables import *
from .filters import *
from .utils import *
from .utils import ensure_product, get_pim_data_for_product, pim_image_url, maybe_notify_pim_error, product_for_sku
from .tasks import sync_main_products_task
from supplier_product_manager.views import UploadSupplierFile

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math
import json
from urllib.parse import urlsplit
import logging

logger = logging.getLogger(__name__)

# Обработка продуктов главного прайса

def sync_main_products(request, **kwargs):
  """Запускает асинхронную синхронизацию MainProduct.

  Refresh, а не redirect на 'mainproducts': кнопка есть и на товарной
  странице, и вернуть человека надо туда, откуда он нажал.
  """
  sync_main_products_task(request.user.id)
  messages.info(request, "Синхронизация запущена")
  return HttpResponseClientRefresh()




def _price_cards(main_product):
  """Все цены строки, пустые тоже — [(поле, подпись, значение)] в порядке MP_PRICES."""
  return [(name, MainProduct._meta.get_field(name).verbose_name, getattr(main_product, name))
          for name in MP_PRICES]


class MainProductInfo(DetailView):
  template_name='mainproduct/partials/info.html'
  model=MainProduct
  def get_template_names(self) -> list[str]:
    if self.request.htmx:
      return [self.template_name + '#partial']
    return super().get_template_names()
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    pim_data = get_pim_data_for_product(self.object, refresh=True)
    maybe_notify_pim_error(self.request.user)
    context['pim_data'] = pim_data
    if pim_data:
      context['pim_image_url'] = pim_image_url(pim_data.get('mainImageId') or pim_data.get('imageId'))
    context['price_cards'] = _price_cards(self.object)
    return context


class MainProductDetail(DetailView):
  template_name='mainproduct/partials/detail.html'
  model=MainProduct
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproduct-info', kwargs=self.kwargs))
    return super().get(request, *args, **kwargs)
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    pim_data = get_pim_data_for_product(self.object, refresh=True)
    maybe_notify_pim_error(self.request.user)
    context['pim_data'] = pim_data
    if pim_data:
      context['pim_image_url'] = pim_image_url(pim_data.get('mainImageId') or pim_data.get('imageId'))
    context['price_cards'] = _price_cards(self.object)
    return context


def _price_rules_by_field(main_product) -> dict:
  """{поле цены: [названия наценок]} — действующие наценки, которые его пишут.

  Подсказка у поля формы: цену, введённую руками, наценка перезапишет при
  следующем пересчёте, и человек должен знать об этом до сохранения.
  """
  from product_price_manager.models import _active_pricetags
  if not main_product.pk:
    return {}
  rules = {}
  tags = (_active_pricetags(timezone.now()).filter(mp=main_product)
          .select_related('p_manager').order_by('dest', 'p_manager__name'))
  for tag in tags:
    rules.setdefault(tag.dest, []).append(tag.p_manager.name if tag.p_manager_id else 'наценка на эту строку')
  return rules


def _after_main_product_saved(product_pks):
  """Основные цены затронутых товаров — сразу, расчётные — общим пересчётом.

  Как у переноса строки ГП в карточке товара (product.views._relinked):
  карточка после перезагрузки уже показывает новые цены.
  """
  from product.services.prices import recalculate_base_prices
  from product_pricing.tasks import update_product_prices_task
  from core.task_runner import dispatch_after_commit
  pks = [pk for pk in set(product_pks) if pk]
  if pks:
    recalculate_base_prices(pks=pks)
  dispatch_after_commit(update_product_prices_task)


class _MainProductFormMixin:
  model = MainProduct
  form_class = MainProductForm
  template_name = 'mainproduct/partials/form.html'

  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['product'] = self.get_preset_product()
    return kwargs

  def get_preset_product(self):
    return None

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    form = context['form']
    rules = _price_rules_by_field(form.instance)
    context['price_rows'] = [(field, rules.get(field.name, [])) for field in form.price_fields]
    context['preset_product'] = self.get_preset_product()
    context['sku_check_url'] = reverse('mainproduct-sku-check')
    context['sku_check_vals'] = json.dumps({'current': form.instance.sku or ''} if form.instance.pk else {})
    return context

  def save_form(self, form):
    form.stamp_updates()
    with transaction.atomic():
      main_product = form.save()
      MainProductLog.objects.bulk_create(form.price_log_entries())
    return main_product


class MainProductCreate(_MainProductFormMixin, CreateView):
  """«Добавить строку ГП»: с «Товаров» (артикул вводится) или из карточки товара.

  Из карточки (?product=<pk>) строка сразу стоит на этом товаре и артикул
  заполнен им. С «Товаров» — строка встаёт на товар со своим артикулом, а
  если такого нет, он создаётся: строки ГП без товара не бывает.
  """

  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('products'))
    return super().get(request, *args, **kwargs)

  def get_preset_product(self):
    if not hasattr(self, '_preset_product'):
      from product.models import Product
      pk = self.request.GET.get('product') or self.request.POST.get('product')
      self._preset_product = get_object_or_404(Product, pk=pk) if pk else None
    return self._preset_product

  def form_valid(self, form):
    product = self.get_preset_product()
    with transaction.atomic():
      self.object = main_product = self.save_form(form)
      if product is not None:
        if not product.number:
          product.number = main_product.sku
          product.save(update_fields=['number'])
        MainProduct.objects.filter(pk=main_product.pk).update(product=product)
        main_product.product = product
      else:
        ensure_product(main_product)
      _after_main_product_saved([main_product.product_id])
    label = main_product.supplier.name if main_product.supplier else 'без поставщика'
    messages.success(self.request, f'Строка ГП «{main_product.name}» ({label}) добавлена')
    # Открыта карточка этого товара — перезагрузить её; иначе (с «Товаров»)
    # — перейти в карточку: там видно новую строку, а на списке она спрятана
    # в свёрнутой панели.
    card_url = reverse('product-detail', kwargs={'pk': main_product.product_id})
    current = urlsplit(self.request.htmx.current_url or '').path
    if current == card_url:
      return HttpResponseClientRefresh()
    return HttpResponseClientRedirect(card_url)


class MainProductUpdate(_MainProductFormMixin, UpdateView):
  """Правка строки ГП — все поля, включая цены.

  Смена артикула переносит строку в товар с новым артикулом (создавая его,
  если нужно): артикул строки и номер товара — одно и то же.
  """

  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproduct-info', kwargs=self.kwargs))
    return super().get(request, *args, **kwargs)

  def form_valid(self, form):
    old_product_pk = form.instance.product_id
    sku_changed = 'sku' in form.changed_data
    with transaction.atomic():
      self.object = main_product = self.save_form(form)
      if sku_changed or not main_product.product_id:
        target = product_for_sku(main_product.sku, main_product.name)
        if target.pk != main_product.product_id:
          MainProduct.objects.filter(pk=main_product.pk).update(product=target)
          main_product.product = target
      _after_main_product_saved([old_product_pk, main_product.product_id])
    messages.success(self.request, 'Строка ГП сохранена')
    return HttpResponseClientRefresh()


class MainProductSkuCheck(View):
  """Подсказка под артикулом в форме: к какому товару встанет строка."""

  def get(self, request, *args, **kwargs):
    from product.models import Product
    sku = (request.GET.get('mp-sku') or '').strip()
    current = request.GET.get('current') or ''
    product = Product.objects.filter(number__iexact=sku).first() if sku else None
    return render(request, 'mainproduct/partials/sku_hint.html', {
      'sku': sku,
      'current': current,
      'product': product,
      'unchanged': bool(current) and sku.lower() == current.strip().lower(),
      'rows_count': product.main_products.count() if product else 0,
    })


class MainProductLogList(SingleTableView):
  model = MainProductLog
  table_class = MainProductLogTable
  template_name = 'mainproduct/partials/logs.html'
  def get_queryset(self):
    qs = (
      super().get_queryset()
      .filter(main_product=self.kwargs.get('pk', None))
      .annotate(
        record_type=Case(
          When(price_type__isnull=False, then=Value('price')),
          default=Value('stock'),
        )
      )
      .order_by('-update_time')
    )
    log_type = self.request.GET.get('log_type', 'all')
    selected_price_type = self.request.GET.get('price_type', '')
    stock_changes_only = self.request.GET.get('stock_changes_only') == 'on'
    row_query = (self.request.GET.get('row_query') or '').strip()

    if log_type == 'price':
      qs = qs.filter(price_type__isnull=False)
    elif log_type == 'stock':
      qs = qs.filter(price_type__isnull=True, stock__isnull=False)

    if selected_price_type:
      qs = qs.filter(price_type=selected_price_type)

    if stock_changes_only:
      qs = qs.filter(price_type__isnull=True, stock__isnull=False)

    if row_query:
      query = Q()
      matched_price_types = [
        price_type for price_type, label in PRICE_TYPES.items()
        if row_query.lower() in label.lower()
      ]
      if matched_price_types:
        query |= Q(price_type__in=matched_price_types)
      if 'остат' in row_query.lower():
        query |= Q(price_type__isnull=True, stock__isnull=False)
      try:
        parsed_number = Decimal(row_query.replace(',', '.'))
        query |= Q(price=parsed_number)
      except InvalidOperation:
        pass
      if row_query.isdigit():
        query |= Q(stock=int(row_query))
      if query:
        qs = qs.filter(query)
      else:
        qs = qs.none()
    return qs

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['mainproduct_pk'] = self.kwargs.get('pk')
    context['selected_log_type'] = self.request.GET.get('log_type', 'all')
    context['selected_price_type'] = self.request.GET.get('price_type', '')
    context['stock_changes_only'] = self.request.GET.get('stock_changes_only') == 'on'
    context['row_query'] = (self.request.GET.get('row_query') or '').strip()
    context['price_type_options'] = [
      (price_type, label) for price_type, label in PRICE_TYPES.items() if price_type
    ]
    return context

  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproduct-info', kwargs=self.kwargs))
    return super().get(request, *args, **kwargs)

