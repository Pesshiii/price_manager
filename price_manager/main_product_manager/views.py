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
from django.db.models import Prefetch, Q, Value, Max, Subquery, OuterRef, IntegerField, ExpressionWrapper, Case, When
from django.db import transaction
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
from supplier_manager.models import Category
from supplier_manager.filters import CategoryFilter
from file_manager.models import FileModel
from core.utils import *
from .forms import *
from .tables import *
from .filters import *
from .utils import *
from .utils import get_pim_data_for_product, prefetch_pim_data, get_file_url, maybe_notify_pim_error
from .tasks import sync_main_products_task
from supplier_product_manager.views import UploadSupplierFile

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math
import json
import logging

logger = logging.getLogger(__name__)

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
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    queryset = context['object_list']
    search_value = self.request.GET.get('search', '')
    filters = {
      name: self.request.GET.getlist(name)
      for name in self.filterset.filters
      if name != 'search' and name in self.request.GET
    }
    logger.info(json.dumps({
      'timestamp': timezone.now().isoformat(),
      'query': search_value,
      'filters': filters,
    }, ensure_ascii=False))
    cat_filter = CategoryFilter(product_qs=queryset, search_query=search_value or None)
    categories = Paginator(cat_filter.qs, 5).page(self.request.GET.get('page', 1))
    context['categories'] =  categories
    context['has_nulled'] = queryset.filter(categories__isnull=True).exists()
    context['nulled_mp_count'] = queryset.filter(categories__isnull=True).count()
    context['column_groups'] = AVAILABLE_COLUMN_GROUPS
    selected_columns = self.request.GET.getlist('columns')
    if selected_columns:
      selected_columns = save_user_columns(self.request.user, selected_columns)
    if not selected_columns:
        selected_columns = load_user_columns(self.request.user)
    if not selected_columns:
        selected_columns = DEFAULT_VISIBLE_COLUMNS
    context['selected_columns'] = selected_columns if selected_columns else DEFAULT_VISIBLE_COLUMNS
    if self.request.htmx and self.request.GET.get('page', 1) == 1:
      self.filterset.build_helper(url=reverse_lazy('mainproducts'))
    return context
  def render_to_response(self, context, **response_kwargs):
    response = super().render_to_response(context, **response_kwargs)
    if self.request.htmx and self.request.GET.get('page', 1) == 1:
      response['Hx-Push'] = self.request.get_full_path()
    return response


class MainProductFilterView(View):
  def get(self, request, *args, **kwargs):
    if not request.htmx:
      return redirect(reverse_lazy('mainproducts'))
    filterset = MainProductFilter(request.GET)
    filterset.build_helper(url=reverse_lazy('mainproducts'))
    return render(request, 'mainproduct/partials/filter.html', {'filter': filterset})


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
    selected_columns = load_user_columns(self.request.user)
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

    qs = MainProductFilter(self.request.GET).qs.prefetch_related('categories').annotate(
      supplier_product_price=Subquery(supplier_price_sq),
      supplier_product_rrp=Subquery(rrp_sq),
      supplier_product_discount_price=Subquery(discount_price_sq),
    )
    if not self.category_pk:
      return qs.filter(categories__isnull=True)
    return qs.filter(categories=Category.objects.get(pk=self.category_pk))
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      context = super().get_context_data(**kwargs)
      if self.category_pk:
        context["category"] = Category.objects.get(pk=self.category_pk)
      table = context.get('table')
      if table is not None:
        try:
          page_records = [row.record for row in table.page.object_list]
        except Exception:
          page_records = []
        table.pim_map = prefetch_pim_data(page_records)
        for data in table.pim_map.values():
          get_file_url(data.get('mainImageId') or data.get('imageId'))
        maybe_notify_pim_error(self.request.user)
      return context


# Обработка продуктов главного прайса

def sync_main_products(request, **kwargs):
  """Запускает асинхронную синхронизацию MainProduct."""
  sync_main_products_task(request.user.id)
  messages.info(request, "Синхронизация запущена")
  return HttpResponseClientRedirect(reverse('mainproducts'))




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
    context['pim_data'] = pim_data
    if pim_data:
      context['pim_image_url'] = get_file_url(pim_data.get('mainImageId') or pim_data.get('imageId'))
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
    context['pim_data'] = pim_data
    if pim_data:
      context['pim_image_url'] = get_file_url(pim_data.get('mainImageId') or pim_data.get('imageId'))
    return context


class MainProductCreate(CreateView):
  model = MainProduct
  form_class = MainProductCreateForm
  template_name = 'mainproduct/partials/create.html'
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproducts'))
    return super().get(request, *args, **kwargs)
  def form_valid(self, form):
    self.object = form.save()
    self.object.rebuild_search_vector()
    return HttpResponseClientRedirect(reverse('mainproduct-detail', kwargs={'pk': self.object.pk}))


class MainProductCreateCategoryTree(View):
  """Lazy-loaded category tree checkboxes for the create-product modal.

  Split out from MainProductCreate so opening the modal doesn't pay for
  building the whole Category tree unless/until the fragment is requested —
  same reasoning as MainProductFilterView being separate from MainPage.
  """
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproducts'))
    form = MainProductCreateForm()
    return render(request, 'supplier/partials/category_filter_field.html', {'field': form['categories']})


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
    if self.request.POST.get('cancel-btn'):
       return HttpResponseClientRedirect(reverse('mainproduct-detail', kwargs=self.kwargs))
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


class MainProductBulkCategoryView(FormView):
  form_class = MainProductBulkCategoryForm
  template_name = 'mainproduct/partials/bulk_category_modal.html'

  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproducts'))
    return super().get(request, *args, **kwargs)

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    queryset = MainProductFilter(self.request.GET).qs
    context['products_count'] = queryset.count()
    context['query_string'] = self.request.GET.urlencode()
    return context

  def form_valid(self, form):
    queryset = MainProductFilter(self.request.GET).qs
    category = form.cleaned_data['category']
    updated_ids = list(queryset.values_list('pk', flat=True))
    updated_count = len(updated_ids)
    if updated_count:
      through = MainProduct.categories.through
      through.objects.bulk_create(
        [through(mainproduct_id=pk, category_id=category.pk) for pk in updated_ids],
        ignore_conflicts=True,
      )
      recalculate_search_vectors(
        MainProduct.objects.filter(pk__in=updated_ids).select_related('supplier', 'manufacturer')
      )
    messages.success(
      self.request,
      f'Категория «{category.name}» добавлена для {updated_count} товар(ов).'
    )
    url = reverse('mainproducts')
    if self.request.GET:
      url = f'{url}?{self.request.GET.urlencode()}'
    return HttpResponseClientRedirect(url)


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
  def get_filterset(self, filterset_class):
      filterset = super().get_filterset(filterset_class)
      url = reverse('mainproduct-resolve', kwargs={'pk':self.kwargs.get('pk')})
      filterset.build_helper(url=url, stripped=bool(self.request.GET.get('bound')))
      return filterset
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
