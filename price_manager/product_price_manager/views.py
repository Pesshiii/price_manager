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
from .models import PriceManager, SpecialPrice
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
  '''Отображение наценок <</price_manager/>>'''
  model = PriceManager
  table_class = PriceManagerListTable
  template_name = 'price_manager/list.html'


def get_price_querry(price_from, price_to, price_prefix):
  if price_from and price_to:
    return Q(**{f'{price_prefix}__range':(price_from, price_to)})
  elif price_from:
    return Q(**{f'{price_prefix}__gte':price_from})
  elif price_to:
    return Q(**{f'{price_prefix}__lte':price_to})
  else:
    return Q()

class PriceManagerCreate(CreateView):
  '''Создание Наценки <<price-manager/create/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  template_name = 'price_manager/partials/create.html'
  def get_success_url(self):
    return resolve_url('pricemanager-create', self.kwargs.get('pk', None))
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    context['supplier'] = Supplier.objects.get(pk=self.kwargs.get('pk'))
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
    messages.success(self.request, 'Менеджер добавлен')
    return HttpResponseClientRefresh()
  


class PriceManagerUpdate(SingleTableMixin, UpdateView):
  '''Обновление Наценки <<price-manager/<int:id>/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  template_name = 'price_manager/partials/create.html'
  def get_success_url(self):
    return resolve_url('pricemanager-create', self.kwargs.get('pk', None))
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    context['supplier'] = Supplier.objects.get(pk=self.kwargs.get('pk'))
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
    messages.success(self.request, 'Менеджер добавлен')
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


def apply_special_price(upm: SpecialPrice):
  mps = MainProduct.objects.filter(id__in=upm.main_products.values_list('id'))
  source = upm.source
  if not upm.source:
    calc_qs = (
      mps.filter(pk=OuterRef("pk"))
      .annotate(
          _changed_price=ExpressionWrapper(
              Ceil(
                  upm.fixed_price,
                  output_field=DecimalField()
              ),
              output_field=DecimalField(),
          )
      )
      .values("_changed_price")[:1]
    )
  elif upm.source in SP_PRICES:
    mps = mps.annotate(source_price=Min(f'supplier_products__{upm.source}'))
    source = 'source_price'
    calc_qs = (
      mps.filter(pk=OuterRef("pk"))
      .annotate(
          _changed_price=ExpressionWrapper(
              Ceil(
                  F(source) * F("supplier__currency__value")
                  * (1 + Decimal(upm.markup) / Decimal(100))
                  + Decimal(upm.increase)
              ),
              output_field=DecimalField(),
          )
      )
      .values("_changed_price")[:1]
    )
  else:
    calc_qs = (
      mps.filter(pk=OuterRef("pk"))
      .annotate(
          _changed_price=ExpressionWrapper(
              Ceil(
                  F(source)
                  * (1 + Decimal(upm.markup) / Decimal(100))
                  + Decimal(upm.increase)
              ),
              output_field=DecimalField(),
          )
      )
      .values("_changed_price")[:1]
    )
  
  mps = mps.annotate(
        changed_price=Subquery(calc_qs, output_field=DecimalField())
    )
  
  
  mps = mps.filter(~Q(**{f'{upm.dest}':F('changed_price')}))

  through = MainProduct.special_prices.through  # промежуточная модель

  # Берём id уже существующих связей, чтобы не дублировать
  existing_ids = set(
      through.objects.filter(
          mainproduct_id__in=mps.values_list('id', flat=True),
          specialprice_id=upm.id,
      ).values_list('mainproduct_id', flat=True)
  )

  # Формируем новые связи

  links = []
  logs = []
  
  for mp in mps:
    if mp.id not in existing_ids:
      links.append(through(mainproduct_id=mp.id, specialprice_id=upm.id))
    logs.append(MainProductLog(
      main_product=mp,
      price_type=upm.dest,
      price=getattr(mp, 'changed_price')
    ))
  through.objects.bulk_create(links, batch_size=1000)
  MainProductLog.objects.bulk_create(logs, ignore_conflicts=True)
  return mps.update(**{f'{upm.dest}':F('changed_price'),
               'price_updated_at':timezone.now()})


class CreateSpecialPrice(CreateView):
  model = SpecialPrice
  fields = '__all__'
  template_name = 'price_manager/partials/create.html'
  def get_success_url(self):
    return reverse('mainproduct-detail', kwargs={'pk':self.kwargs.get('pk', None)})
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproduct-info', kwargs=self.kwargs))
    return super().get(request, *args, **kwargs)
  def form_valid(self, form):
    if form.cleaned_data['source'] is None:
      if form.cleaned_data['fixed_price'] is None:
        messages.error(self.request, 'Для фиксированной цены необходимо указать значение фиксированной цены')
        return self.form_invalid(form)
    elif form.cleaned_data['source'] == form.cleaned_data['dest']:
      messages.error(self.request, 'Цена не может считаться от себя же')
      return self.form_invalid(form)
    if not form.cleaned_data['dest']:
      messages.error(self.request, 'Если указана исходная цена, то необходимо указать целевую цену')
      return self.form_invalid(form)
    if self.kwargs.get('pk', None):
      obj = form.save()
      MainProduct.objects.get(id=self.kwargs.get('pk')).special_prices.add(obj.id)
      messages.success(self.request, 'Наценка сохранена')
    else:
      messages.error(self.request, 'Главный товар неопознан')
    return super().form_valid(form)
  
  

class SpecialPriceList(TemplateView):
  '''Отображение наценок <</price_manager/>>'''
  template_name = 'price_manager/partials/list.html'
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['mainproduct'] = MainProduct.objects.get(pk=self.kwargs.get('pk',None))
    context['specialprices'] = SpecialPrice.objects.filter(main_products=self.kwargs.get('pk',None))
    return context

class UpdateSpecialPrice(UpdateView):
  model = SpecialPrice
  fields = '__all__'
  template_name = 'price_manager/partials/update.html'
  def get_success_url(self):
    return reverse('mainproduct-detail', kwargs={'pk':self.kwargs.get('pk', None)})
  def get(self, request, *args, **kwargs):
    if not self.request.htmx:
      return redirect(reverse('mainproduct-info', kwargs=self.kwargs))
    return super().get(request, *args, **kwargs)
  def form_valid(self, form):
    if form.cleaned_data['source'] is None:
      if form.cleaned_data['fixed_price'] is None:
        messages.error(self.request, 'Для фиксированной цены необходимо указать значение фиксированной цены')
        return self.form_invalid(form)
    elif form.cleaned_data['source'] == form.cleaned_data['dest']:
      messages.error(self.request, 'Цена не может считаться от себя же')
      return self.form_invalid(form)
    if not form.cleaned_data['dest']:
      messages.error(self.request, 'Если указана исходная цена, то необходимо указать целевую цену')
      return self.form_invalid(form)
    if self.kwargs.get('pk', None):
      obj = form.save()
      MainProduct.objects.get(id=self.kwargs.get('pk')).special_prices.add(obj.id)
      messages.success(self.request, 'Наценка сохранена')
    else:
      messages.error(self.request, 'Главный товар неопознан')
    return super().form_valid(form)