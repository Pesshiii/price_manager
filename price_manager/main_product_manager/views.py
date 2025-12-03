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
                                  FormView,
                                  TemplateView)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from typing import Optional, Any, Dict, Iterable
from collections import defaultdict, OrderedDict
from django.db.models import Count, Prefetch
from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView, FilterMixin
from dal import autocomplete

# Импорты моделей, функций, форм, таблиц
from .models import *
from supplier_product_manager.models import SupplierProduct
from supplier_manager.models import Discount
from file_manager.models import FileModel
from core.functions import *
from .forms import *
from .tables import *
from .filters import *
from product_price_manager.views import apply_price_manager, apply_unique_price_manager

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math


def build_category_tree(categories):
  children_map = defaultdict(list)
  for category in categories:
    children_map[category.parent_id].append(category)
  for siblings in children_map.values():
    siblings.sort(key=lambda item: item.name.lower())
  def build_nodes(parent_id):
    nodes = []
    for category in children_map.get(parent_id, []):
      nodes.append({
          'category': category,
          'children': build_nodes(category.id)
      })
    return nodes
  return build_nodes(None)


def _collect_int_values(values):
  result = set()
  for value in values:
    try:
      result.add(int(value))
    except (TypeError, ValueError):
      continue
  return result


def _expand_category_ids_with_ancestors(category_ids):
  expanded_ids = set(category_ids)
  to_process = {category_id for category_id in expanded_ids if category_id is not None}
  while to_process:
    parents = set(
        Category.objects
        .filter(id__in=to_process)
        .values_list('parent_id', flat=True)
    )
    parents.discard(None)
    new_ids = parents - expanded_ids
    if not new_ids:
      break
    expanded_ids.update(new_ids)
    to_process = new_ids
  expanded_ids.discard(None)
  return expanded_ids


def _get_search_filtered_queryset(request):
  filter_data = request.GET.copy()
  for field in ('category', 'supplier', 'manufacturer'):
    filter_data.pop(field, None)
  filter_data.pop('page', None)
  filterset = MainProductFilter(data=filter_data, queryset=MainProduct.objects.all())
  return filterset.qs


def get_main_filter_context(request):
  filterset = MainProductFilter(data=request.GET or None, queryset=MainProduct.objects.all())
  filter_form = filterset.form

  queryset = _get_search_filtered_queryset(request)

  selected_supplier_ids = _collect_int_values(request.GET.getlist('supplier'))
  selected_manufacturer_ids = _collect_int_values(request.GET.getlist('manufacturer'))
  selected_category_ids = _collect_int_values(request.GET.getlist('category'))

  supplier_ids = set(queryset.values_list('supplier_id', flat=True))
  supplier_ids.discard(None)
  supplier_ids.update(selected_supplier_ids)

  manufacturer_ids = set(queryset.values_list('manufacturer_id', flat=True))
  manufacturer_ids.discard(None)
  manufacturer_ids.update(selected_manufacturer_ids)

  category_ids = set(queryset.values_list('category_id', flat=True))
  category_ids.discard(None)
  category_ids.update(selected_category_ids)
  category_ids = _expand_category_ids_with_ancestors(category_ids)

  supplier_queryset = Supplier.objects.filter(id__in=supplier_ids).order_by('name') if supplier_ids else Supplier.objects.none()
  manufacturer_queryset = Manufacturer.objects.filter(id__in=manufacturer_ids).order_by('name') if manufacturer_ids else Manufacturer.objects.none()
  category_queryset = Category.objects.filter(id__in=category_ids).select_related('parent') if category_ids else Category.objects.none()

  filter_form.fields['supplier'].queryset = supplier_queryset
  filter_form.fields['manufacturer'].queryset = manufacturer_queryset
  filter_form.fields['category'].queryset = category_queryset

  available_suppliers = list(supplier_queryset)
  available_manufacturers = list(manufacturer_queryset)

  selected_categories = {str(value) for value in request.GET.getlist('category') if value}

  category_tree = build_category_tree(list(category_queryset))

  return {
      'filter_form': filter_form,
      'category_tree': category_tree,
      'selected_categories': selected_categories,
      'available_suppliers': available_suppliers,
      'available_manufacturers': available_manufacturers,
  }


class MainPage(SingleTableMixin, FilterView):
  model = MainProduct
  filterset_class = MainProductFilter
  table_class = MainProductListTable
  template_name = 'main/main.html'
  table_pagination = False

  def get_table(self, **kwargs):
    return super().get_table(**kwargs, request=self.request)

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    filter_context = get_main_filter_context(self.request)
    context.update(filter_context)

    filterset = context.get('filter')
    category_tables = []

    if filterset is not None:
      filtered_records = filterset.qs.select_related('category')

      if len(filtered_records) > 10000:
        category_table = self.table_class(filtered_records, request=self.request)
        RequestConfig(self.request).configure(category_table)
        category_tables.append({
            'category': Category.objects.none(),
            'table': category_table,
        })
      else:
        grouped_records = OrderedDict()
        grouped_records[None] = {
                  'category': Category.objects.none(),
                  'records': list(filtered_records.filter(category__isnull=True))
              }
        for category in Category.objects.all():
          if not list(filtered_records.filter(category=category)) == []:
            grouped_records[category.pk] = {
                  'category': category,
                  'records': list(filtered_records.filter(category=category))
              }
        sorted_groups = sorted(
            grouped_records.values(),
            key=lambda item: (
                item['category'] is None,
                (item['category'].name.lower() if item['category'] else ''),
            )
        )

        for group in sorted_groups:
          category_table = self.table_class(group['records'], request=self.request)
          RequestConfig(self.request, paginate=False).configure(category_table)
          category_tables.append({
              'category': group['category'],
              'table': category_table,
          })

    context['category_tables'] = category_tables

    filter_form = filter_context['filter_form']
    dynamic_url = reverse('main-filter-options')
    hx_attrs = {
        'hx-get': dynamic_url,
        'hx-target': '#filters-update-sink',
        'hx-include': '#main-filter-form',
    }

    search_field = filter_form.fields['search']
    search_field.widget.attrs.update({
        **hx_attrs,
        'hx-trigger': 'keyup changed delay:500ms',
        'autocomplete': 'off',
    })

    anti_search_field = filter_form.fields['anti_search']
    anti_search_field.widget.attrs.update({
        **hx_attrs,
        'hx-trigger': 'keyup changed delay:500ms',
        'autocomplete': 'off',
    })

    if 'available' in filter_form.fields:
      filter_form.fields['available'].widget.attrs.update({
          **hx_attrs,
          'hx-trigger': 'change',
      })

    context['table_update_url'] = reverse('main-table')
    return context


class MainFilterOptionsView(View):
  template_name = 'main/includes/dynamic_filters.html'

  def get(self, request, *args, **kwargs):
    context = get_main_filter_context(request)
    return render(request, self.template_name, context)


class MainTableView(MainPage):
  template_name = 'main/includes/table.html'

  
# Обработка продуктов главного прайса

class MainProductUpdate(UpdateView):
    model = MainProduct
    form_class = MainProductForm
    template_name = 'main/product/update.html'
    success_url = '/'
    pk_url_kwarg = 'id'

def sync_main_products(request, **kwargs):
  """Обновляет остатки и применяет наценки в MainProduct из SupplierProduct"""
  updated = 0
  errors = 0

  supplier_products = SupplierProduct.objects.select_related("main_product").all()

  mps = []

  for sp in supplier_products:
    try:
      if not sp.main_product or sp.main_product.stock == sp.stock:
        continue  # пропускаем без связи
      mp = sp.main_product
      mp.stock = sp.stock
      mp.stock_updated_at = sp.supplier.stock_updated_at
      text = mp._build_search_text()
      mp.search_vector = SearchVector(Value(text), config='russian')
      mps.append(mp)
    except Exception as ex:
      errors += 1
      messages.error(request, f"Ошибка при обновлении {sp}: {ex}")
  updated = MainProduct.objects.bulk_update(mps, ['stock', 'stock_updated_at', 'manufacturer', 'category', 'search_vector'])
  MainProductLog.objects.bulk_create([MainProductLog(main_product=mp, stock=mp.stock) for mp in mps])
  messages.success(request, f"Остатки обновлены у {updated} товаров, ошибок: {errors}")
  for upm in UniquePriceManager.objects.all():
    apply_unique_price_manager(upm)
  for price_manager in PriceManager.objects.all():
    apply_price_manager(price_manager)
  messages.success(request, 'Наценки применены')
  return redirect('main')
