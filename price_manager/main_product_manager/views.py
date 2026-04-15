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
from collections import defaultdict, OrderedDict
from django.db.models import Count, Prefetch, F, Q, Value, Max, Min, Subquery, OuterRef, IntegerField, ExpressionWrapper
from django.db import transaction
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
from .functions import *
from product_price_manager.views import update_prices
from supplier_product_manager.views import UploadSupplierFile

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math

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
    if selected_columns:
      selected_columns = save_user_columns(self.request.user, selected_columns)
    if not selected_columns:
        selected_columns = load_user_columns(self.request.user)
    if not selected_columns:
        selected_columns = DEFAULT_VISIBLE_COLUMNS
    context['selected_columns'] = selected_columns if selected_columns else DEFAULT_VISIBLE_COLUMNS
    return context
  def render_to_response(self, context, **response_kwargs):
    response = super().render_to_response(context, **response_kwargs)
    if self.request.htmx and self.request.GET.get('page', 1) == 1:
      response['Hx-Push'] = self.request.get_full_path()
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
    return super().get_queryset().filter(main_product=self.kwargs.get('pk', None))
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
      MainProduct.objects.filter(pk__in=updated_ids).update(category=category)
      recalculate_search_vectors(
        MainProduct.objects.filter(pk__in=updated_ids).select_related('supplier', 'category', 'manufacturer')
      )
    messages.success(
      self.request,
      f'Категория «{category.name}» назначена для {updated_count} товар(ов).'
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

    def get(self, request, *args, **kwargs):
        
        if not request.htmx:
            return super().get(request, *args, **kwargs)

        return HttpResponseClientRedirect(f"{reverse('mainproduct-duplicates')}?{request.META['QUERY_STRING']}")
    def _get_selected_compare_fields(self, request):
        return [
            field for field in DUPLICATE_LOOKUPS.keys()
            if request.GET.get('c' + field) == 'on'
        ]


    def post(self, request, *args, **kwargs):
        selected_compare_fields = self._get_selected_compare_fields(request)
        merge_mode = request.POST.get('merge_mode', 'selected')
        if merge_mode == 'all':
            if not selected_compare_fields:
                messages.warning(request, 'Сначала выберите хотя бы одно поле сравнения.')
                return redirect(f"{reverse('mainproduct-duplicates')}?{request.META['QUERY_STRING']}")


            duplicate_values = (
                MainProductFilter(request.GET).qs.values(*selected_compare_fields)
                .annotate(Count('id')).filter(id__count__gt=1).order_by(*selected_compare_fields)
            )

            if not duplicate_values.exists():
                messages.info(request, 'Группы дубликатов по текущему фильтру не найдены.')
                return redirect(f"{reverse('mainproduct-duplicates')}?{request.META['QUERY_STRING']}")

            merged_groups = 0
            deleted_products_total = 0
            moved_supplier_products_total = 0
            moved_logs_total = 0
            processed_ids = set()

            for value in duplicate_values:
                query = Q()
                for field in selected_compare_fields:
                    query &= Q(**{field:value[field]})
                buffer_queryset = MainProduct.objects.filter(query).annotate(oldest_log_at=Min('mp_log__update_time')).order_by('oldest_log_at')
                merged_data = merge_selected_main_products(buffer_queryset.values_list('id', flat=True))
                if merged_data is None:
                    continue
                _, deleted_products, moved_supplier_products, moved_logs = merged_data
                merged_groups += 1
                deleted_products_total += deleted_products
                moved_supplier_products_total += moved_supplier_products
                moved_logs_total += moved_logs
                processed_ids.update(buffer_queryset.values_list('id', flat=True))
            if merged_groups == 0:
                messages.info(request, 'Не удалось объединить найденные группы дубликатов.')
            else:
                messages.success(
                    request,
                    (
                        f'Объединено групп: {merged_groups}. '
                        f'Удалено дублей: {deleted_products_total}. '
                        f'Перенесено товаров поставщиков: {moved_supplier_products_total}. '
                        f'Перенесено логов: {moved_logs_total}.'
                    ),
                )
            return redirect(f"{reverse('mainproduct-duplicates')}?{request.META['QUERY_STRING']}")

        selected_products = [int(pk) for pk in request.POST.getlist('selected_products') if pk.isdigit()]
        if len(selected_products) < 2:
            messages.warning(request, 'Выберите минимум два товара для объединения. Или хотя бы одну группу.')
            return redirect(reverse_lazy('mainproduct-duplicates'))

        selected_ids = list(dict.fromkeys(selected_products))
        if len(selected_ids) < 2:
            messages.warning(request, 'Не удалось собрать минимум два товара для объединения.')
            return redirect(f"{reverse('mainproduct-duplicates')}?{request.META['QUERY_STRING']}")

        selection_query = request.POST.urlencode()
        if request.META['QUERY_STRING']:
            selection_query = f"{selection_query}&{request.META['QUERY_STRING']}"
        return redirect(f"{reverse('mainproduct-duplicate-select-keep')}?{selection_query}")
    def get_filterset_kwargs(self, filterset_class):
        selected_compare_fields = self._get_selected_compare_fields(self.request)
        kwargs = super().get_filterset_kwargs(filterset_class)
        kwargs['url'] = f"{reverse('mainproduct-duplicates')}?{'&'.join(['c' + lable + '=on' for lable in selected_compare_fields])}"
        kwargs['hx_target']=None
        kwargs['bound_ignore']=True
        return kwargs
  
    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        selected_compare_fields = self._get_selected_compare_fields(self.request)
        context['selected_compare_fields'] = selected_compare_fields
        context['comparison_labels'] = [
            DUPLICATE_LOOKUPS[field]['verbose_name'] for field in selected_compare_fields
        ]
        return context


class MainProductDuplicateSelectionView(TemplateView):
    template_name = 'mainproduct/duplicate_selection.html'

    def build_return_query(self, querydict):
        query_copy = querydict.copy()
        for key in ['selected_products', 'keep_product_id', 'redirect_query']:
            query_copy.pop(key, None)
        return query_copy.urlencode()

    def get_selected_products(self):
        selected_ids = [int(pk) for pk in self.request.GET.getlist('selected_products') if pk.isdigit()]
        return list(
            MainProduct.objects
            .filter(id__in=selected_ids)
            .annotate(oldest_log_at=Min('mp_log__update_time'))
            .order_by(F('oldest_log_at').asc(nulls_last=True), 'id')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['products'] = self.get_selected_products()
        context['return_query'] = self.build_return_query(self.request.GET)
        return context

    def get(self, request, *args, **kwargs):
        products = self.get_selected_products()
        if len(products) < 2:
            messages.warning(request, 'Выберите минимум два товара для объединения.')
            query_string = self.build_return_query(request.GET)
            return redirect(f"{reverse('mainproduct-duplicates')}?{query_string}" if query_string else reverse('mainproduct-duplicates'))
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        selected_products = [int(pk) for pk in request.POST.getlist('selected_products') if pk.isdigit()]
        keep_product_id = request.POST.get('keep_product_id')
        
        if len(selected_products) < 2:
            messages.warning(request, 'Выберите минимум два товара для объединения.')
            return redirect(reverse_lazy('mainproduct-duplicates'))
        
        if not keep_product_id or not keep_product_id.isdigit():
            messages.warning(request, 'Выберите товар, который нужно оставить.')
            return redirect(f"{reverse('mainproduct-duplicate-select-keep')}?{request.POST.urlencode()}")
        
        merged_data = merge_selected_main_products(selected_products, keep_product_id=int(keep_product_id))
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

        redirect_query = request.POST.get('redirect_query', '')
        return redirect(f"{reverse('mainproduct-duplicates')}?{redirect_query}" if redirect_query else reverse('mainproduct-duplicates'))
  


def mainproductdupe(request, id):
    if id == None:
        messages.info(request, 'Все товары обработаны')
        return render(request, 'mainproduct/partials/duplicates_partial.html', context={'products':None, 'id':id})
    
    qfilter = MainProductFilter(request.GET)
    selected_compare_fields = [
      field for field in DUPLICATE_LOOKUPS.keys()
      if request.GET.get('c' + field) == 'on'
    ]
    if selected_compare_fields == []:
        return render(request, 'mainproduct/partials/duplicates_partial.html', context={'products':None, 'id':None})
    duplicate_values = (
            qfilter.qs.values(*selected_compare_fields)
            .annotate(Count('id')).filter(id__count__gt=1).order_by(*selected_compare_fields)
        )[id:]
    if not duplicate_values.exists():
        messages.info(request, 'Все товары обработаны')
        return render(request, 'mainproduct/partials/duplicates_partial.html', context={'products':None, 'id':None})
    query = Q()
    for field in selected_compare_fields:
       query &= Q(**{field:duplicate_values.first()[field]})
    buffer_queryset = MainProduct.objects.filter(query).annotate(oldest_log_at=Min('mp_log__update_time'))
    return render(request, 'mainproduct/partials/duplicates_partial.html', context={'products':buffer_queryset, 'id':id+1})
