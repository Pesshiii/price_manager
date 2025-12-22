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
from dal import autocomplete
from django.db.models import Q, F, ExpressionWrapper, BooleanField, DurationField, Value, Case, When
from django.db.models.functions import Greatest, ExtractDay

# Импорты моделей, функций, форм, таблиц
from .models import *
from file_manager.models import FileModel
from core.functions import *
from main_product_manager.models import MainProduct, MP_PRICES
from .forms import *
from .tables import *
from .filters import *



class CategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        
        qs = Category.objects.all()

        if self.q:
            qs = qs.filter(name__icontains=self.q)

        return qs


# Обработка поставщика

class SupplierList(ListView):
  '''Список поставщиков на <<supplier/>>'''
  model = Supplier
  template_name = 'supplier/list.html'
  context_object_name = 'suppliers'
  def get_queryset(self):
    queryset = super().get_queryset().prefetch_related('main_products')
    now = timezone.now()
    queryset = queryset.annotate(
      time_delta=ExpressionWrapper(
        ExtractDay(Greatest(now - F('stock_updated_at'), now - F('price_updated_at'))),
        DurationField()
        ),
      )
    stock_rate = [When(stock_update_rate=text, then=val) for text, val in TIME_FREQ.items()]
    price_rate = [When(price_update_rate=text, then=val) for text, val in TIME_FREQ.items()]
    queryset = queryset.annotate(stock_rate_conv=Case(*stock_rate, default=None))
    queryset = queryset.annotate(price_rate_conv=Case(*price_rate, default=None))
    queryset = queryset.annotate(
      danger=ExpressionWrapper(
        Case(
          When(time_delta__gte=F('stock_rate_conv'), then=True),
          When(time_delta__gte=F('price_rate_conv'), then=True),
          default=False),
        output_field=BooleanField()
        )
      )
    queryset = queryset.annotate(total=Count('main_products'))
    queryset = queryset.annotate(
      basic_price=Count(
        'main_products', 
        filter=Q(main_products__basic_price__isnull=True)|Q(main_products__basic_price=0)
        ))
    queryset = queryset.annotate(
      m_price=Count(
        'main_products', 
        filter=Q(main_products__m_price__isnull=True)|Q(main_products__m_price=0)
        ))
    queryset = queryset.annotate(
      wholesale_price=Count(
        'main_products', 
        filter=Q(main_products__wholesale_price__isnull=True)|Q(main_products__wholesale_price=0)
        ))
    queryset = queryset.annotate(
      prime_cost=Count(
        'main_products', 
        filter=Q(main_products__prime_cost__isnull=True)|Q(main_products__prime_cost=0)
        ))
    queryset = queryset.order_by('name')

    return queryset
  


class SupplierCreate(CreateView):
  '''Таблица создания Поставщиков <<supplier/create/>>'''
  model = Supplier
  fields = SUPPLIER_SPECIFIABLE_FIELDS
  success_url = '/supplier'
  template_name = 'supplier/create.html'


class SupplierDelete(DeleteView):
  model = Supplier
  success_url = '/supplier/'
  pk_url_kwarg = 'id'
  template_name = 'supplier/confirm_delete.html'

class SupplierUpdate(UpdateView):
  '''Таблица  обновления Поставщиков <<supplier/update/>>'''
  model = Supplier
  fields = SUPPLIER_SPECIFIABLE_FIELDS
  success_url = '/supplier'
  template_name = 'supplier/update.html'
  pk_url_kwarg='id'

class ManufacturerList(SingleTableView):
  '''Отображение производителей <<manufacturer/>>'''
  model = Manufacturer
  table_class = ManufacturerListTable
  template_name = 'manufacturer/list.html'

class ManufacturerDetail(SingleTableView):
  '''Отображение словоря производителя <<manufacturer/<int:id>/>>'''
  model = ManufacturerDict
  table_class = ManufacturerDictListTable
  template_name = 'manufacturer/dict.html'
  def get_table_data(self):
    return ManufacturerDict.objects.filter(manufacturer_id=self.kwargs['id'])
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['manufacturer_id'] = self.kwargs['id']
    context['manufacturer'] = Manufacturer.objects.get(id=context['manufacturer_id'])
    return context

class ManufacturerCreate(CreateView):
  '''Создание Производителя <<manufacturer/create/>>'''
  model = Manufacturer
  fields = '__all__'
  success_url = '/manufacturer/'
  template_name = 'manufacturer/create.html'

class ManufacturerDictCreate(CreateView):
  '''Обновление словаря Производителя <<manufacturer/<int:id>/add-alt/>>'''
  model = ManufacturerDict
  form_class = ManufacturerDictForm
  template_name = 'manufacturer/create.html'
  def get_form(self):
    form = super().get_form()
    form.fields['manufacturer'].initial = Manufacturer.objects.get(id=self.kwargs['id'])
    return form
  def get_success_url(self):
    return reverse('manufacturer-detail',kwargs={'id':self.kwargs['id']})

# Обработка валюты

class CurrencyList(SingleTableView):
  '''Отображает валюты <</currency/>>'''
  model = Currency
  table_class=CurrencyListTable
  template_name = 'currency/list.html'
  def get_table_data(self):
    return Currency.objects.exclude(name='KZT')

class CurrencyCreate(CreateView):
  model = Currency
  fields = '__all__'
  template_name = 'currency/create.html'
  def get_success_url(self):
    return '/currency/'

class CurrencyUpdate(UpdateView):
  model = Currency
  fields = '__all__'
  template_name = 'currency/update.html'
  pk_url_kwarg = 'id'
  def get_success_url(self):
    return '/currency/'
