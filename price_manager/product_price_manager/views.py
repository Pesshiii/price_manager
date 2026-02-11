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
from .models import PriceManager
from file_manager.models import FileModel
from core.functions import *
from main_product_manager.models import MainProduct, MainProductLog, MP_PRICES
from .forms import *
from .tables import *
from .filters import *

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math

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
  


class PriceManagerCreate(CreateView):
  '''Создание Наценки <<price-manager/create/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  template_name = 'price_manager/partials/create.html'
  def get_success_url(self):
    return resolve_url('pricemanager-create', self.kwargs.get('pk', None))
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    supplier = Supplier.objects.get(pk=self.kwargs.get('pk'))
    context['supplier'] = supplier
    context['form'].fields['discounts'].queryset = supplier.discounts
    context['form'].fields['categories'].queryset = Category.objects.filter(pk__in=MainProduct.objects.select_related('supplierproducts', 'category').filter(supplierproducts__in=supplier.supplierproducts.all()).values('category'))
    return context
  def form_invalid(self, form):
    messages.error(self.request, 'Ошибка')
    response = super().form_invalid(form)
    return response
  def form_valid(self, form):
    cd = form.cleaned_data
    if cd['price_fixed'] and cd['fixed_price'] == 0:
      form.add_error(field=None, error='Не указана фиксированная цена')
      return self.form_invalid(form)
    if not cd['price_fixed']:
      if not cd['source']:
        form.add_error(field='source', error='Поле от какой цены считать должно быть указано')
        return self.form_invalid(form)
      if cd['source'] == cd['dest']:
        form.add_error(field=None, error='Поля от какой цены считать и какую цену считать совпадают')
        return self.form_invalid(form)
      if (cd['price_from'] and cd['price_to']
        and cd['price_from'] >= cd['price_to']):
        form.add_error(field=None, error='Неверный диапозон цены')
        return self.form_invalid(form)
    instance = form.save(commit=False)
    instance.supplier = Supplier.objects.get(pk=self.kwargs.get('pk'))
    if cd['price_fixed']:
      instance.source = 'fixed_price'
    instance.save()
    for discount in instance.discounts.filter(~Q(pk__in=cd['discounts'])):
      instance.discounts.remove(discount)
    for discount in cd['discounts']:
      instance.discounts.add(discount)
    for category in instance.categories.filter(~Q(pk__in=cd['categories'])):
      instance.categories.remove(category)
    for category in cd['categories']:
      instance.categories.add(category)
    messages.success(self.request, 'Менеджер добавлен')
    return HttpResponseClientRefresh()
  


class PriceManagerUpdate(SingleTableMixin, UpdateView):
  '''Обновление Наценки <<price-manager/<int:pk>/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  template_name = 'price_manager/partials/update.html'
  def dispatch(self, request, *args, **kwargs):
    self.instance = PriceManager.objects.get(pk=self.kwargs.get('pk', None))
    return super().dispatch(request, *args, **kwargs)
  def get_success_url(self):
    return resolve_url('pricemanager-update', self.kwargs.get('pk', None))
  def form_invalid(self, form):
    response = super().form_invalid(form)
    return response
  def post(self, request, *args, **kwargs):
    if request.POST.get('delete', None) == 'true':
      self.instance.delete()
      return HttpResponseClientRefresh()
    return super().post(request, *args, **kwargs)
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    context['form'].initial['price_fixed'] = self.instance.source=='fixed_price'
    context['form'].fields['discounts'].queryset = self.instance.supplier.discounts
    return context
  def form_valid(self, form):
    cd = form.cleaned_data
    if cd['price_fixed'] and cd['fixed_price'] == 0:
      form.add_error(field=None, error='Не указана фиксированная цена')
      return self.form_invalid(form)
    if not cd['price_fixed']:
      if not cd['source']:
        form.add_error(field='source', error='Поле от какой цены считать должно быть указано')
        return self.form_invalid(form)
      if cd['source'] == cd['dest']:
        form.add_error(field=None, error='Поля от какой цены считать и какую цену считать совпадают')
        return self.form_invalid(form)
      if (cd['price_from'] and cd['price_to']
        and cd['price_from'] >= cd['price_to']):
        form.add_error(field=None, error='Неверный диапозон цены')
        return self.form_invalid(form)
    instance = form.save(commit=False)
    if cd['price_fixed']:
      instance.source = 'fixed_price'
    instance.save()
    for discount in instance.discounts.filter(~Q(pk__in=cd['discounts'])):
      instance.discounts.remove(discount)
    for discount in cd['discounts']:
      instance.discounts.add(discount)
    for category in instance.categories.filter(~Q(pk__in=cd['categories'])):
      instance.categories.remove(category)
    for category in cd['categories']:
      instance.categories.add(category)
    messages.success(self.request, 'Обновления менеджера сохранены')
    return HttpResponseClientRefresh()
  


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
    context['pricetags'] = PriceTag.objects.filter(mp=self.kwargs.get('pk',None))
    return context

class PriceTagCreate(CreateView):
  model = PriceTag
  form_class = PriceTagForm
  template_name = 'price_manager/partials/pricetag_create.html'
  def get_success_url(self):
    return resolve_url('mainproduct-detail', self.kwargs.get('pk', None))
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    context['mainproduct'] = MainProduct.objects.get(pk=self.kwargs.get('pk'))
    return context
  def form_invalid(self, form):
    messages.error(self.request, 'Ошибка')
    response = super().form_invalid(form)
    return response
  def form_valid(self, form):
    cd = form.cleaned_data
    if cd['price_fixed'] and cd['fixed_price'] == 0:
      form.add_error(field=None, error='Не указана фиксированная цена')
      return self.form_invalid(form)
    if not cd['price_fixed']:
      if not cd['source']:
        form.add_error(field='source', error='Поле от какой цены считать должно быть указано')
        return self.form_invalid(form)
      if cd['source'] == cd['dest']:
        form.add_error(field=None, error='Поля от какой цены считать и какую цену считать совпадают')
        return self.form_invalid(form)
    instance = form.save(commit=False)
    instance.mp = MainProduct.objects.get(pk=self.kwargs.get('pk'))
    if cd['price_fixed']:
      instance.source = 'fixed_price'
    instance.save()
    messages.success(self.request, 'Менеджер добавлен')
    return HttpResponseClientRefresh()
  
  


class PriceTagUpdate(UpdateView):
  model = PriceTag
  form_class = PriceTagForm
  template_name = 'price_manager/partials/pricetag_update.html'
  def get(self, request, *args, **kwargs):
    self.instance = PriceTag.objects.get(pk=self.kwargs.get('pk', None))
    return super().get(request, *args, **kwargs)
  def get_success_url(self):
    return resolve_url('mainproduct-detail', PriceTag.objects.get(pk=self.kwargs.get('pk', None)).mp.pk)
  def form_invalid(self, form):
    messages.error(self.request, 'Ошибка')
    response = super().form_invalid(form)
    return response
  def get_context_data(self, **kwargs) -> dict[str, Any]:
      context = super().get_context_data(**kwargs)
      context["form"].initial['price_fixed'] = self.instance.source=='fixed_price'
      return context
  def form_valid(self, form):
    cd = form.cleaned_data
    if cd['price_fixed'] and cd['fixed_price'] == 0:
      form.add_error(field=None, error='Не указана фиксированная цена')
      return self.form_invalid(form)
    if not cd['price_fixed']:
      if not cd['source']:
        form.add_error(field='source', error='Поле от какой цены считать должно быть указано')
        return self.form_invalid(form)
      if cd['source'] == cd['dest']:
        form.add_error(field=None, error='Поля от какой цены считать и какую цену считать совпадают')
        return self.form_invalid(form)
    instance = form.save(commit=False)
    if cd['price_fixed']:
      instance.source = 'fixed_price'
    instance.save()
    messages.success(self.request, 'Менеджер добавлен')
    return HttpResponseClientRefresh()