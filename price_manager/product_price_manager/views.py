from supplier_product_manager.models import SupplierProduct, SP_PRICES
from supplier_product_manager.tables import SupplierProductPriceManagerTable
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
from django.db.models import Q

# Импорты моделей, функций, форм, таблиц
from .models import PriceManager
from file_manager.models import FileModel
from core.functions import *
from main_product_manager.models import MainProduct, MP_PRICES
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

class PriceManagerCreate(SingleTableMixin, CreateView):
  '''Создание Наценки <<price-manager/create/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  table_class = SupplierProductPriceManagerTable
  success_url = '/price-manager/'
  template_name = 'price_manager/create.html'
  def get_success_url(self):
    return f'/price-manager'
  def get_table_data(self):
    products = SupplierProduct.objects.all()
    if not hasattr(self, 'cleaned_data'):
      return products
    cleaned_data = self.cleaned_data
    products = products.filter(
      supplier=cleaned_data['supplier'])
    if not cleaned_data['has_rrp'] is None:
      if cleaned_data['has_rrp']:
        products = products.filter(rrp__gt=0)
      else:
        products = products.filter(rrp=0)

    if cleaned_data['discounts']:
      products = products.filter(
        discounts__in=cleaned_data['discounts'])
    if cleaned_data['source'] in SP_PRICES:
      products = products.filter(get_price_querry(
        cleaned_data['price_from'],
        cleaned_data['price_to'],
        cleaned_data['source']))
    elif cleaned_data['source'] in MP_PRICES:
      products = products.filter(get_price_querry(
        cleaned_data['price_from'],
        cleaned_data['price_to'],
        f'''main_product__{cleaned_data['source']}'''))
    return products
  def get_form(self):
    form = super().get_form(self.form_class)
    discounts = Discount.objects.all()
    discounts = discounts.filter(supplier=form['supplier'].value())
    choices = [(None, 'Все группы скидок')]
    choices.extend([(disc.id, disc.name) for disc in discounts])
    form.fields['discounts'].choices = choices
    return form
  def form_valid(self, form):
    if not form.is_valid(): return self.form_invalid(form)
    cleaned_data = form.cleaned_data
    self.cleaned_data = cleaned_data
    if cleaned_data['dest'] == cleaned_data['source']:
      messages.error(self.request, f'Поле не может считатсься от себя же')
      return self.form_invalid(form)
    price_from = cleaned_data['price_from']
    price_to = cleaned_data['price_to']
    if price_from and price_to:
      if price_from>=price_to:
        messages.error(self.request, f'''Неверная ценовая зона: "От" больше или равен "До"''')
        return self.form_invalid(form)
    if price_to and price_to==0:
      messages.error(self.request, f'''Неверная ценовая зона: "До" равен 0''')
      return self.form_invalid(form)
    query = Q()
    if price_from and price_to:
      if price_from == 0:
        query |= Q(price_from__isnull=True)
      else:
        query |= (Q(price_from__gte=price_from)
                  &Q(price_from__lte=price_to))
      query |= (Q(price_to__gte=price_from)
                &Q(price_to__lte=price_to))
      query |= (Q(price_to__isnull=True)&Q(price_from__lte=price_to))
    elif price_to:
      query |= Q(price_from__lte=price_to)
      query |= Q(price_from__isnull=True)
    elif price_from:
      query |= Q(price_to__gte=price_from)
      query |= Q(price_to__isnull=True)
    conf_price_manager = PriceManager.objects.filter(query)
    if cleaned_data['discounts']:
      conf_price_manager = conf_price_manager.filter(
      Q(discounts__in=cleaned_data['discounts'])|
      Q(discounts__isnull=True))
    if cleaned_data['has_rrp'] is None:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp__isnull=True)|Q(has_rrp=True)|Q(has_rrp=False))
    elif cleaned_data['has_rrp']:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp=True)|Q(has_rrp__isnull=True))
    else:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp=False)|Q(has_rrp__isnull=True))
    conf_price_manager = conf_price_manager.filter(
      dest=cleaned_data['dest'])
    conf_price_manager = conf_price_manager.filter(supplier=cleaned_data['supplier'])
    if conf_price_manager.exists():
      messages.error(self.request, f'Пересечение с другой наценкой: {conf_price_manager.first().name}')
      return self.form_invalid(form)
    if not self.request.POST.get('btn') == 'save': return self.form_invalid(form)
    form.save()
    messages.success(self.request, 'Наценка успешно добавлена')
    return super().form_invalid(form)
  


class PriceManagerUpdate(SingleTableMixin, UpdateView):
  '''Обновление Наценки <<price-manager/<int:id>/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  table_class = SupplierProductPriceManagerTable
  success_url = '/price-manager/'
  template_name = 'price_manager/create.html'
  pk_url_kwarg = 'id'
  def get_success_url(self):
    return f'/price-manager'
  def get_table_data(self):
    products = SupplierProduct.objects.all()
    if not hasattr(self, 'cleaned_data'):
      return products
    cleaned_data = self.cleaned_data
    products = products.filter(
      supplier=cleaned_data['supplier'])
    if not cleaned_data['has_rrp'] is None:
      if cleaned_data['has_rrp']:
        products = products.filter(rrp__gt=0)
      else:
        products = products.filter(rrp=0)

    if cleaned_data['discounts']:
      products = products.filter(
        discounts__in=cleaned_data['discounts'])
    if cleaned_data['source'] in SP_PRICES:
      products = products.filter(get_price_querry(
        cleaned_data['price_from'],
        cleaned_data['price_to'],
        cleaned_data['source']))
    elif cleaned_data['source'] in MP_PRICES:
      products = products.filter(get_price_querry(
        cleaned_data['price_from'],
        cleaned_data['price_to'],
        f'''main_product__{cleaned_data['source']}'''))
    return products
  def get_form(self):
    form = super().get_form(self.form_class)
    discounts = Discount.objects.all()
    discounts = discounts.filter(supplier=form['supplier'].value())

    choices = [(None, 'Все группы скидок')]
    choices.extend([(disc.id, disc.name) for disc in discounts])
    if not form.fields['discounts'].choices == choices:
      form.fields['discounts'].choices = choices
    return form
  def form_valid(self, form):
    if not form.is_valid(): return self.form_invalid(form)
    cleaned_data = form.cleaned_data
    self.cleaned_data = cleaned_data
    if cleaned_data['dest'] == cleaned_data['source']:
      messages.error(self.request, f'Поле не может считатсься от себя же')
      return self.form_invalid(form)
    price_from = cleaned_data['price_from']
    price_to = cleaned_data['price_to']
    if price_from and price_to:
      if price_from>=price_to:
        messages.error(self.request, f'''Неверная ценовая зона: "От" больше или равен "До"''')
        return self.form_invalid(form)
    if price_to==0:
      messages.error(self.request, f'''Неверная ценовая зона: "До" равен 0''')
      return self.form_invalid(form)
    query = Q()
    if price_from and price_to:
      if price_from == 0:
        query |= Q(price_from__isnull=True)
      else:
        query |= (Q(price_from__gte=price_from)
                  &Q(price_from__lte=price_to))
      query |= (Q(price_to__gte=price_from)
                &Q(price_to__lte=price_to))
      query |= (Q(price_to__isnull=True)&Q(price_from__lte=price_to))
    elif price_to:
      query |= Q(price_from__lte=price_to)
      query |= Q(price_from__isnull=True)
    elif price_from:
      query |= Q(price_to__gte=price_from)
      query |= Q(price_to__isnull=True)
    conf_price_manager = PriceManager.objects.filter(query)
    conf_price_manager = conf_price_manager.filter(~Q(id=self.kwargs.get('id')))
    if cleaned_data['discounts']:
      conf_price_manager = conf_price_manager.filter(
      Q(discounts__in=cleaned_data['discounts'])|
      Q(discounts__isnull=True))
    if cleaned_data['has_rrp'] is None:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp__isnull=True)|Q(has_rrp=True)|Q(has_rrp=False))
    elif cleaned_data['has_rrp']:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp=True)|Q(has_rrp__isnull=True))
    else:
      conf_price_manager = conf_price_manager.filter(Q(has_rrp=False)|Q(has_rrp__isnull=True))
    conf_price_manager = conf_price_manager.filter(
      dest=cleaned_data['dest'])
    conf_price_manager = conf_price_manager.filter(supplier=cleaned_data['supplier'])
    if conf_price_manager.exists():
      messages.error(self.request, f'Пересечение с другой наценкой: {conf_price_manager.first().name}')
      return self.form_invalid(form)
    if not self.request.POST.get('btn') == 'save': return self.form_invalid(form)
    form.save()
    messages.success(self.request, 'Наценка успешно обновлена')
    return super().form_invalid(form)


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

def apply_price_manager(price_manager: PriceManager):
  products = SupplierProduct.objects.all()
  products = products.filter(
    supplier=price_manager.supplier)
  if not price_manager.has_rrp is None:
    if price_manager.has_rrp:
      products = products.filter(rrp__gt=0)
    else:
      products = products.filter(rrp=0)

  discounts = list(price_manager.discounts.values_list('id'))
  if not discounts == []:
    products = products.filter(
      discounts__in=discounts)
    


  if price_manager.source in SP_PRICES:
    products = products.filter(get_price_querry(
      price_manager.price_from,
      price_manager.price_to,
      price_manager.source))
  elif price_manager.source in MP_PRICES:
    products = products.filter(get_price_querry(
      price_manager.price_from,
      price_manager.price_to,
      f'''main_product__{price_manager.source}'''))
  mps = []
  for product in products:
    main_product = product.main_product
    main_product.price_managers.add(price_manager)

    setattr(main_product, 
            price_manager.dest, 
            math.ceil(getattr(
              product if price_manager.source in SP_PRICES else main_product, price_manager.source, 0)*main_product.supplier.currency.value*(1+price_manager.markup/100)+price_manager.increase))
    main_product.price_updated_at = timezone.now()
    mps.append(main_product)
  MainProduct.objects.bulk_update(mps, fields=[price_manager.dest, 'price_updated_at'])
  
