from supplier_product_manager.models import SupplierProduct, SP_PRICES
from supplier_product_manager.tables import SupplierProductPriceManagerTable
# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404)
from django.core.paginator import Paginator
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
from django.db.models import Q, F, ExpressionWrapper, BooleanField, DurationField, Value, Case, When
from django.db.models.functions import Greatest, ExtractDay


from dal import autocomplete
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh, retarget

# Импорты моделей, функций, форм, таблиц
from .models import *
from file_manager.models import FileModel
from core.functions import *
from main_product_manager.models import MainProduct, MP_PRICES
from .forms import *
from .tables import *
from .filters import *

from datetime import timedelta



class CategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        
        qs = Category.objects.all()

        if self.q:
            qs = qs.filter(name__icontains=self.q)

        return qs


# Обработка поставщика

class SupplierList(TemplateView):
  '''Список поставщиков на <<supplier/>>'''
  template_name = 'supplier/list.html'
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    now = timezone.now()
    context = super().get_context_data(**kwargs)
    def price_filter(price): 
      return Q(**{f'{price}__isnull':True})|Q(**{f'{price}':0})
    # queryset = Paginator(Supplier.objects.all(), 5).page(1).object_list.prefetch_related('main_products')
    queryset = Supplier.objects.all()
    context["suppliers"] = list(
       map(lambda obj: {
          'pk': obj.pk,
          'name':obj.name,
          'danger':  obj.stock_updated_at and timedelta(weeks=TIME_FREQ[obj.stock_update_rate]) <= now - obj.stock_updated_at or
                     obj.price_updated_at and  timedelta(weeks=TIME_FREQ[obj.price_update_rate]) <= now - obj.price_updated_at,
          'total': obj.main_products.count(),
          'price_updated_at':obj.price_updated_at if obj.price_updated_at else 'Отсутствует',
          'stock_updated_at':obj.stock_updated_at if obj.stock_updated_at else 'Отсутствует',
          'basic_price': obj.main_products.filter(price_filter('basic_price')).count(),
          'wholesale_price': obj.main_products.filter(price_filter('wholesale_price')).count(),
          'm_price': obj.main_products.filter(price_filter('m_price')).count(),
          'prime_cost': obj.main_products.filter(price_filter('prime_cost')).count(),
        }, queryset))
    return context



class SupplierCreate(CreateView):
  '''Таблица создания Поставщиков <<supplier/create/>>'''
  model = Supplier
  form_class=SupplierForm
  success_url = '/supplier'
  template_name = 'supplier/partials/create.html'
  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['url'] = reverse('supplier-create')
    return kwargs
  def form_valid(self, form):
    response = super().form_valid(form)
    return HttpResponseClientRedirect(reverse('supplier'))
  


class SupplierDelete(DeleteView):
  model = Supplier
  success_url = '/supplier/'
  pk_url_kwarg = 'id'
  template_name = 'supplier/confirm_delete.html'

class SupplierUpdate(UpdateView):
  '''Таблица  обновления Поставщиков <<supplier/update/>>'''
  model = Supplier
  form_class = SupplierForm
  template_name = 'supplier/partials/update.html'
  pk_url_kwarg='pk'
  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['url'] = reverse('supplier-update', kwargs={'pk':self.kwargs.get('pk')})
    return kwargs
  def get_template_names(self) -> list[str]:
      if self.request.htmx:
          return [self.template_name+"#form_partial"]
      return super().get_template_names()
  def get_success_url(self):
    return reverse('supplier-update', kwargs={'pk':self.kwargs.get('pk')})
  
  def form_valid(self, form):
    messages.success(self.request, 'Настройки поставщика сохранены.')
    return super().form_valid(form)
  

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
