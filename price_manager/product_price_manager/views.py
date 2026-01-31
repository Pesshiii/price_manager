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
from django.db.models import (F, ExpressionWrapper, 
                              fields, Func, 
                              Value, Min,
                              Q, DecimalField,
                              OuterRef, Subquery)
from django.db.models.functions import Ceil

from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin

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

class PriceManagerCreate(SingleTableMixin, CreateView):
  '''Создание Наценки <<price-manager/create/>>'''
  model = PriceManager
  form_class = PriceManagerForm
  table_class = SupplierProductPriceManagerTable
  success_url = '/price-manager/'
  template_name = 'price_manager/create.html'
  def get_initial(self):
    initial = super().get_initial()
    supplier_id = self.request.GET.get('supplier')
    if supplier_id:
      initial['supplier'] = supplier_id
    return initial
  def get_success_url(self):
    return f'/price-manager'
  def get_table_data(self):
    products = SupplierProduct.objects.all()
    if not hasattr(self, 'cleaned_data'):
      supplier_id = self.request.GET.get('supplier')
      if supplier_id:
        return products.filter(supplier=supplier_id)
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
    supplier_id = self.request.GET.get('supplier')
    if supplier_id:
      form.initial['supplier'] = supplier_id
    discounts = Discount.objects.all()
    discounts = discounts.filter(supplier=form['supplier'].value())
    choices = [(disc.id, disc.name) for disc in discounts]
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
  
  print(mps)
  
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

def apply_price_manager(price_manager: PriceManager):


  ## Следует убрать после обновления в главной ветке ###

  if price_manager.source == 'rmp':
    price_manager.source = 'rrp'
    price_manager.save()

  ######################################################


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
  
  mps = MainProduct.objects.filter(id__in=products.values_list('main_product__id'))
  source = price_manager.source
  if price_manager.source in SP_PRICES:
    mps = mps.annotate(source_price=Min(f'supplier_products__{price_manager.source}'))
    source = 'source_price'
    calc_qs = (
      mps.filter(pk=OuterRef("pk"))
      .annotate(
          _changed_price=ExpressionWrapper(
              Ceil(
                  F(source) * F("supplier__currency__value")
                  * (1 + Decimal(price_manager.markup) / Decimal(100))
                  + Decimal(price_manager.increase)
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
                  * (1 + Decimal(price_manager.markup) / Decimal(100))
                  + Decimal(price_manager.increase)
              ),
              output_field=DecimalField(),
          )
      )
      .values("_changed_price")[:1]
    )
  
  mps = mps.annotate(
        changed_price=Subquery(calc_qs, output_field=DecimalField())
    )

  mps = mps.filter(~Q(**{f'{price_manager.dest}':F('changed_price')}))

  
  through = MainProduct.price_managers.through  # промежуточная модель

  # Берём id уже существующих связей, чтобы не дублировать
  existing_ids = set(
      through.objects.filter(
          mainproduct_id__in=mps.values_list('id', flat=True),
          pricemanager_id=price_manager.id,
      ).values_list('mainproduct_id', flat=True)
  )

  # Формируем новые связи

  links = []
  logs = []
  
  for mp in mps:
    if mp.id not in existing_ids:
      links.append(through(mainproduct_id=mp.id, pricemanager_id=price_manager.id))
    logs.append(MainProductLog(
      main_product=mp,
      price_type=price_manager.dest,
      price=getattr(mp, 'changed_price')
    ))
  through.objects.bulk_create(links, batch_size=1000)
  MainProductLog.objects.bulk_create(logs)
  return mps.update(**{price_manager.dest:F('changed_price'),
               'price_updated_at':timezone.now()})

def update_prices(request):
  count = 0
  for price_manager in PriceManager.objects.all():
    count += apply_price_manager(price_manager)
  for upm in SpecialPrice.objects.all():
    count += apply_special_price(upm)
  
  messages.success(request, f'Наценки применены. Изменено товаров: {count}')

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
  
