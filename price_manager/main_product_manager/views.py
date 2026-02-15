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
from django.db.models import Count, Prefetch, F, Q, Value, Max, Subquery, OuterRef, IntegerField, ExpressionWrapper
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


class ResolveMainproduct(FilterView):
  model = MainProduct
  filterset_class = MainProductFilter
  template_name = 'mainproduct/partials/resolve_list.html'
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return HttpResponseClientRedirect(reverse('mainproduct-detail', kwargs={'pk':self.kwargs.get('pk')}))
    return super().get(request, *args, **kwargs)
  def get_filterset_kwargs(self, filterset_class):
      kwargs = super().get_filterset_kwargs(filterset_class)
      # Add your custom kwarg here
      kwargs['url'] = reverse('mainproduct-resolve-table', kwargs={'pk': self.kwargs.get('pk')}) 
      return kwargs
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      context = super().get_context_data(**kwargs)
      context["pk"] = self.kwargs.get('pk')
      return context
  



class MainProductResolveTableView(SingleTableView):
  table_class=MainProductResolveTable
  template_name='mainproduct/partials/table.html'
  model = MainProduct
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return HttpResponseClientRedirect(reverse_lazy('mainproducts'))
    return super().get(request, *args, **kwargs)
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      context = super().get_context_data(**kwargs)
      context["pk"] = self.kwargs.get('pk')
      return context
  
  def get_table(self, **kwargs):
    return super().get_table(
      **kwargs,
      request=self.request,
      url=reverse('mainproduct-resolve-table', kwargs={'pk':self.kwargs.get('pk')})
    )
  def get_table_data(self):
    return MainProductFilter(self.request.GET).qs