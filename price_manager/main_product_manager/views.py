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
from django.urls import reverse, reverse_lazy
from typing import Optional, Any, Dict, Iterable
from collections import defaultdict
from django.db.models import Count, Prefetch, F, Q, Value, Max, Min, Subquery, OuterRef, IntegerField, ExpressionWrapper, Exists
from django.db import transaction
from django.db.models.functions import Lower, Trim, StrIndex
from django.contrib.postgres.search import SearchVector
# Импорты из сторонних приложений
from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView, FilterMixin
from django.core.paginator import Paginator
from django.http import HttpResponse

from dal import autocomplete
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh, retarget
from django.template.context_processors import csrf
from crispy_forms.utils import render_crispy_form


# Импорты моделей, функций, форм, таблиц
from .models import *
from supplier_product_manager.models import SupplierProduct
from supplier_manager.models import Category
from file_manager.models import FileModel
from core.functions import *
from .forms import *
from .tables import *
from .filters import *
from product_price_manager.views import update_prices
from supplier_product_manager.views import UploadSupplierFile

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math


def _normalize_compare_string(value: Optional[str]) -> str:
  return re.sub(r'\s+', ' ', (value or '').strip().lower())


def _names_partially_match(left_name: Optional[str], right_name: Optional[str]) -> bool:
  left_normalized = _normalize_compare_string(left_name)
  right_normalized = _normalize_compare_string(right_name)
  if not left_normalized or not right_normalized:
    return False
  return (
    left_normalized in right_normalized
    or right_normalized in left_normalized
  )


def _build_name_pair_query(products: list['MainProduct']) -> list[list['MainProduct']]:
  duplicates_groups: list[list[MainProduct]] = []
  visited_ids = set()
  product_by_id = {product.id: product for product in products}

  for product in products:
    if product.id in visited_ids:
      continue

    stack = [product.id]
    component_ids = set()
    while stack:
      current_id = stack.pop()
      if current_id in component_ids:
        continue
      component_ids.add(current_id)
      current_product = product_by_id[current_id]

      for candidate in products:
        if candidate.id in component_ids:
          continue
        if _names_partially_match(current_product.normalized_name, candidate.normalized_name):
          stack.append(candidate.id)

    if len(component_ids) > 1:
      visited_ids.update(component_ids)
      duplicates_groups.append([
        product_by_id[product_id] for product_id in sorted(component_ids)
      ])

  return duplicates_groups


def build_duplicates_groups(
  base_queryset,
  selected_compare_fields: list[str],
) -> list[list['MainProduct']]:
  if not selected_compare_fields:
    return []

  if 'name' not in selected_compare_fields:
    grouped_values = (
      base_queryset
      .values(*selected_compare_fields)
      .annotate(products_count=Count('id'))
      .filter(products_count__gt=1)
    )

    duplicates_groups = []
    for group_data in grouped_values:
      query = Q()
      for field in selected_compare_fields:
        query &= Q(**{field: group_data[field]})
      duplicates_groups.append(list(base_queryset.filter(query)))
    return duplicates_groups

  exact_fields = [field for field in selected_compare_fields if field != 'name']
  grouped_values = (
    base_queryset
    .values(*exact_fields)
    .annotate(products_count=Count('id'))
    .filter(products_count__gt=1)
  )

  duplicates_groups: list[list[MainProduct]] = []
  for group_data in grouped_values:
    group_query = Q()
    for field in exact_fields:
      group_query &= Q(**{field: group_data[field]})

    group_queryset = base_queryset.filter(group_query)

    related_products = MainProduct.objects.annotate(
      normalized_name=Lower(Trim(F('name')))
    ).filter(group_query).exclude(pk=OuterRef('pk'))

    has_partial_name_match = Exists(
      related_products.annotate(
        reverse_match_position=StrIndex(OuterRef('normalized_name'), F('normalized_name')),
      ).filter(
        Q(normalized_name__contains=OuterRef('normalized_name')) |
        Q(reverse_match_position__gt=0)
      )
    )

    group_products = list(
      group_queryset
      .annotate(normalized_name=Lower(Trim(F('name'))))
      .annotate(has_partial_name_match=has_partial_name_match)
      .filter(has_partial_name_match=True)
    )

    if len(group_products) > 1:
      duplicates_groups.extend(_build_name_pair_query(group_products))

  return duplicates_groups

class MainPage(FilterView):
  model = MainProduct
  filterset_class = MainProductFilter
  template_name = 'mainproduct/list.html'
  def get_template_names(self) -> list[str]:
      if self.request.htmx:
        if not self.request.GET.get('page', 1) == 1:
          return ["mainproduct/partials/tables_bycat.html#category-table"]
        return ["mainproduct/partials/tables_bycat.html"]
      return super().get_template_names()
  def get_filterset_kwargs(self, filterset_class):
      kwargs = super().get_filterset_kwargs(filterset_class)
      # Add your custom kwarg here
      kwargs['url'] = reverse_lazy('mainproducts')
      if not self.request.htmx:
        kwargs['bound_ignore']=True
      return kwargs
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    queryset = context['object_list']
    categories = Paginator(
        Category.objects.filter(
        pk__in=queryset.prefetch_related('category').values_list('category__pk')
      ).prefetch_related(
        'mainproducts'
      ).annotate(
        mps_count=Count(F('mainproducts'))
      ).filter(~Q(mps_count=0)),
      5
    ).page(self.request.GET.get('page', 1))
    context['categories'] =  categories
    context['has_nulled'] = queryset.filter(category__isnull=True).exists()
    context['nulled_mp_count'] = queryset.filter(category__isnull=True).count()
    context['column_groups'] = AVAILABLE_COLUMN_GROUPS
    selected_columns = self.request.GET.getlist('columns')
    context['selected_columns'] = selected_columns if selected_columns else DEFAULT_VISIBLE_COLUMNS
    return context
  def render_to_response(self, context, **response_kwargs):
    response = super().render_to_response(context, **response_kwargs)
    if self.request.htmx and self.request.GET.get('page', 1) == 1:
      response['Hx-Push'] = self.request.build_absolute_uri()
    return response


class MainProductTableView(SingleTableView):
  table_class=MainProductTable
  template_name='mainproduct/partials/table.html'
  model = MainProduct
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse_lazy('mainproducts'))
    return super().get(request, *args, **kwargs)
  def get_table(self, **kwargs):
    self.category_pk = self.kwargs.get('category_pk', None)
    if self.category_pk:
      url = reverse('mainproduct-table-bycat',kwargs={'category_pk': self.category_pk})
    else:
      url = reverse('mainproduct-table-nocat')
    selected_columns = self.request.GET.getlist('columns')
    return super().get_table(
      **kwargs,
      request=self.request,
      url=url,
      selected_columns=selected_columns,
      prefix=f'{self.category_pk if self.category_pk else 0}-'
    )
  def get_table_data(self):
    supplier_price_sq = SupplierProduct.objects.filter(
      main_product=OuterRef('pk')
    ).order_by('-updated_at').values('supplier_price')[:1]
    rrp_sq = SupplierProduct.objects.filter(
      main_product=OuterRef('pk')
    ).order_by('-updated_at').values('rrp')[:1]
    discount_price_sq = SupplierProduct.objects.filter(
      main_product=OuterRef('pk')
    ).order_by('-updated_at').values('discount_price')[:1]

    qs = MainProductFilter(self.request.GET).qs.prefetch_related('category').annotate(
      supplier_product_price=Subquery(supplier_price_sq),
      supplier_product_rrp=Subquery(rrp_sq),
      supplier_product_discount_price=Subquery(discount_price_sq),
    )
    if not self.category_pk:
      return qs.filter(category__isnull=True)
    return qs.filter(category=Category.objects.get(pk=self.category_pk))
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      context = super().get_context_data(**kwargs)
      if self.category_pk:
        context["category"] = Category.objects.get(pk=self.category_pk)
      return context


# Обработка продуктов главного прайса

def sync_main_products(request, **kwargs):
  """Обновляет остатки и применяет наценки в MainProduct из SupplierProduct"""
  Category.objects.rebuild()
  messages.info(
    request, 
    f"Векторы поиска обновлены у {recalculate_search_vectors(MainProduct.objects.filter(search_vector__isnull=True)) or 0} товаров")
  count, dcount = update_prices()
  messages.info(request, f"Цены обновлены у {count} товаров. Обнулены у {dcount} товаров.")
  messages.info(request, f"Остатки обновлены у {update_stocks()} товаров")
  
  return HttpResponseClientRedirect(reverse('mainproducts'))




class MainProductInfo(DetailView):
  template_name='mainproduct/partials/info.html'
  model=MainProduct
  def get_template_names(self) -> list[str]:
    if self.request.htmx:
      return [self.template_name + '#partial']
    return super().get_template_names()
  
  


class MainProductDetail(DetailView):
  template_name='mainproduct/partials/detail.html'
  model=MainProduct
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproduct-info', kwargs=self.kwargs))
    return super().get(request, *args, **kwargs)
  

class MainProductUpdate(UpdateView):
  model = MainProduct
  form_class = MainProductForm
  template_name = 'mainproduct/partials/update.html'
  def get_success_url(self):
    return reverse('mainproduct-info', kwargs=self.kwargs)
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproduct-info', kwargs=self.kwargs))
    return super().get(request, *args, **kwargs)
  def form_valid(self, form):
    if form.is_valid():
      form.save()
      return HttpResponseClientRedirect(reverse('mainproduct-detail', kwargs=self.kwargs))
    else:
      return redirect(reverse('mainproduct-update', kwargs=self.kwargs))

class MainProductLogList(SingleTableView):
  model = MainProductLog
  table_class = MainProductLogTable
  template_name = 'mainproduct/partials/logs.html'
  def get_queryset(self):
    return super().get_queryset().filter(main_product=self.kwargs.get('pk', None))
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproduct-info', kwargs=self.kwargs))
    return super().get(request, *args, **kwargs)


class ResolveMainproduct(SingleTableMixin, FilterView):
  model = MainProduct
  filterset_class = MainProductFilter
  table_class=MainProductResolveTable
  template_name = 'mainproduct/partials/resolve_list.html'
  def get_template_names(self) -> list[str]:
      if not self.request.GET.get('page', None):
        if not self.request.GET.get('bound', None):
          return [self.template_name]
        else:
          return [self.template_name + '#partialtableblock']
      return [self.template_name + '#partialtable']
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return HttpResponseClientRedirect(reverse('mainproduct-detail', kwargs={'pk':self.kwargs.get('pk')}))
    return super().get(request, *args, **kwargs)
  def get_filterset_kwargs(self, filterset_class):
      kwargs = super().get_filterset_kwargs(filterset_class)
      url=reverse('mainproduct-resolve', kwargs={'pk':self.kwargs.get('pk')})
      kwargs['url'] = url
      return kwargs
  def get_table_kwargs(self):
    kwargs = super().get_table_kwargs()
    kwargs['request'] = self.request
    kwargs['url'] = reverse('mainproduct-resolve', kwargs={'pk':self.kwargs.get('pk')})
    return kwargs
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      context = super().get_context_data(**kwargs)
      context["pk"] = self.kwargs.get('pk')
      context["bound"] = self.request.GET.get('bound', None) is not None
      return context


class MainProductDuplicatesView(FilterView):
  model = MainProduct
  filterset_class = MainProductFilter
  template_name = 'mainproduct/duplicates.html'

  COMPARISON_FIELD_LABELS = {
    'article': 'артиклю',
    'supplier': 'поставщику',
    'name': 'названию',
  }

  def get_filterset_kwargs(self, filterset_class):
    kwargs = super().get_filterset_kwargs(filterset_class)
    kwargs['url'] = reverse_lazy('mainproduct-duplicates')
    return kwargs

  def post(self, request, *args, **kwargs):
    selected_products = [int(pk) for pk in request.POST.getlist('selected_products') if pk.isdigit()]
    if len(selected_products) < 2:
      messages.warning(request, 'Выберите минимум два товара для объединения.')
      return redirect(reverse_lazy('mainproduct-duplicates'))

    merged_data = merge_selected_main_products(selected_products)
    if merged_data is None:
      messages.warning(request, 'Не удалось объединить выбранные товары.')
      return redirect(reverse_lazy('mainproduct-duplicates'))

    keep_product, deleted_products, moved_supplier_products, moved_logs = merged_data
    messages.success(
      request,
      (
        f'Товары объединены в "{keep_product.name}" (ID: {keep_product.id}). '
        f'Удалено дублей: {deleted_products}. '
        f'Перенесено товаров поставщиков: {moved_supplier_products}. '
        f'Перенесено логов: {moved_logs}.'
      ),
    )
    return redirect(reverse_lazy('mainproduct-duplicates'))

  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)

    selected_compare_fields = [
      field for field in self.COMPARISON_FIELD_LABELS.keys()
      if self.request.GET.get(field) == 'on'
    ]
    context['selected_compare_fields'] = selected_compare_fields

    duplicates_groups: list[list[MainProduct]] = []
    if selected_compare_fields:
      base_queryset = (
        context['filter'].qs
        .select_related('supplier', 'manufacturer', 'category')
        .annotate(oldest_log_at=Min('mp_log__update_time'))
        .order_by(F('oldest_log_at').asc(nulls_last=True), 'id')
      )
      duplicates_groups = build_duplicates_groups(base_queryset, selected_compare_fields)

    context['duplicates_groups'] = duplicates_groups
    context['comparison_labels'] = [
      self.COMPARISON_FIELD_LABELS[field] for field in selected_compare_fields
    ]
    return context


def merge_selected_main_products(selected_ids: list[int]):
  products = list(
    MainProduct.objects
    .filter(id__in=selected_ids)
    .annotate(oldest_log_at=Min('mp_log__update_time'))
    .order_by(F('oldest_log_at').asc(nulls_last=True), 'id')
  )
  if len(products) < 2:
    return None

  keep_product = products[0]
  duplicate_ids = [product.id for product in products[1:]]
  if not duplicate_ids:
    return None

  with transaction.atomic():
    moved_supplier_products = SupplierProduct.objects.filter(
      main_product_id__in=duplicate_ids
    ).update(main_product=keep_product)

    duplicate_logs = MainProductLog.objects.filter(
      main_product_id__in=duplicate_ids,
    ).values(
      'update_time',
      'price',
      'price_type',
      'stock',
    )

    moved_logs = MainProductLog.objects.bulk_create(
      [
        MainProductLog(
          update_time=log['update_time'],
          main_product=keep_product,
          price=log['price'],
          price_type=log['price_type'],
          stock=log['stock'],
        )
        for log in duplicate_logs
      ],
      ignore_conflicts=True,
    )

    deleted_products = MainProduct.objects.filter(id__in=duplicate_ids).delete()[0]

  return (keep_product, deleted_products, moved_supplier_products, len(moved_logs))
  
