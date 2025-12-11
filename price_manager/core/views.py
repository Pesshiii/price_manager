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

# Импорты моделей, функций, форм, таблиц
from core.models import *
from file_manager.models import FileModel
from .functions import *
from .forms import *
from .tables import *
from .filters import *

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math


class AppLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            existing_classes = field.widget.attrs.get('class', '')
            classes = [cls for cls in existing_classes.split() if cls]
            if 'form-control' not in classes:
                classes.append('form-control')
            field.widget.attrs['class'] = ' '.join(classes) if classes else 'form-control'
        return form


class AppLogoutView(LogoutView):
    next_page = 'login'


class ShoppingTabListView(LoginRequiredMixin, TemplateView):
  template_name = 'shopping_tab/list.html'
  form_class = ShopingTabCreateForm

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    form = kwargs.get('form')
    context['form'] = form if form is not None else self.form_class()
    context['tabs'] = (
      ShopingTab.objects
      .filter(user=self.request.user)
      .annotate(product_count=Count('products', distinct=True))
      .order_by('name')
    )
    context['products'] = {tab.name: [product for product in tab.products.all()] for tab in context['tabs']}
    return context

  def post(self, request, *args, **kwargs):
    form = self.form_class(request.POST)
    if form.is_valid():
      name = form.cleaned_data['name']
      if ShopingTab.objects.filter(user=request.user, name=name).exists():
        form.add_error('name', 'Корзина с таким названием уже существует.')
      else:
        tab = form.save(commit=False)
        tab.user = request.user
        tab.save()
        messages.success(request, 'Корзина создана.')
        return redirect('shopping-tab-list')
    return self.render_to_response(self.get_context_data(form=form))


class ShoppingTabDeleteView(LoginRequiredMixin, View):
  def post(self, request, pk):
    tab = get_object_or_404(ShopingTab, pk=pk, user=request.user)
    tab.delete()
    messages.success(request, 'Корзина удалена.')
    return redirect('shopping-tab-list')


class ShoppingTabDetailView(LoginRequiredMixin, UpdateView):
  model = ShopingTab
  form_class = ShopingTabUpdateForm
  template_name = 'shopping_tab/detail.html'
  context_object_name = 'tab'

  def get_queryset(self):
    return super().get_queryset().filter(user=self.request.user)

  def form_valid(self, form):
    messages.success(self.request, 'Корзина обновлена.')
    return super().form_valid(form)

  def get_success_url(self):
    return reverse('shopping-tab-detail', kwargs={'pk': self.object.pk})

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['products'] = (
      self.object.products.select_related('main_product')
      .order_by('name')
    )
    return context


class ShoppingTabProductCreateView(LoginRequiredMixin, View):
  template_name = 'shopping_tab/product_form.html'
  form_class = AlternateProductForm

  def dispatch(self, request, *args, **kwargs):
    self.tab = get_object_or_404(ShopingTab, pk=kwargs['tab_pk'], user=request.user)
    return super().dispatch(request, *args, **kwargs)

  def get_context(self, form):
    return {
      'form': form,
      'tab': self.tab,
      'is_update': False,
    }

  def get(self, request, *args, **kwargs):
    form = self.form_class()
    return render(request, self.template_name, self.get_context(form))

  def post(self, request, *args, **kwargs):
    form = self.form_class(request.POST)
    if form.is_valid():
      name = form.cleaned_data['name']
      main_product = form.cleaned_data.get('main_product')
      alternate_product, _ = AlternateProduct.objects.get_or_create(
        name=name,
        main_product=main_product,
      )
      if self.tab.products.filter(pk=alternate_product.pk).exists():
        messages.info(request, 'Этот товар уже есть в корзине.')
      else:
        self.tab.products.add(alternate_product)
        messages.success(request, 'Товар добавлен в корзину.')
      return redirect('shopping-tab-detail', pk=self.tab.pk)
    return render(request, self.template_name, self.get_context(form))


class ShoppingTabProductUpdateView(LoginRequiredMixin, UpdateView):
  model = AlternateProduct
  form_class = AlternateProductForm
  template_name = 'shopping_tab/product_form.html'
  context_object_name = 'alternate_product'
  pk_url_kwarg = 'product_pk'

  def dispatch(self, request, *args, **kwargs):
    self.tab = get_object_or_404(ShopingTab, pk=kwargs['tab_pk'], user=request.user)
    return super().dispatch(request, *args, **kwargs)

  def get_queryset(self):
    return super().get_queryset().filter(shoping_tabs=self.tab)

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['tab'] = self.tab
    context['is_update'] = True
    return context

  def form_valid(self, form):
    messages.success(self.request, 'Данные товара обновлены.')
    return super().form_valid(form)

  def get_success_url(self):
    return reverse('shopping-tab-detail', kwargs={'pk': self.tab.pk})


class ShoppingTabProductDeleteView(LoginRequiredMixin, View):
  def post(self, request, tab_pk, pk):
    tab = get_object_or_404(ShopingTab, pk=tab_pk, user=request.user)
    product = get_object_or_404(AlternateProduct, pk=pk, shoping_tabs=tab)
    tab.products.remove(product)
    if not product.shoping_tabs.exists():
      product.delete()
    messages.success(request, 'Товар удален из корзины.')
    return redirect('shopping-tab-detail', pk=tab.pk)


class ShoppingTabSelectionView(LoginRequiredMixin, TemplateView):
  template_name = 'shopping_tab/add_to_tab_modal.html'

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    product = get_object_or_404(MainProduct, pk=self.kwargs['product_id'])
    tabs = (
      ShopingTab.objects
      .filter(user=self.request.user)
      .annotate(product_count=Count('products', distinct=True))
      .prefetch_related(
        Prefetch(
          'products',
          queryset=AlternateProduct.objects.select_related('main_product').order_by('name')
        )
      )
      .order_by('name')
    )
    existing_tab_ids = set(
      AlternateProduct.objects
      .filter(main_product=product, shoping_tabs__user=self.request.user)
      .values_list('shoping_tabs__id', flat=True)
    )
    context.update({
      'product': product,
      'tabs': tabs,
      'existing_tab_ids': existing_tab_ids,
    })
    return context


class ShoppingTabAddProductView(LoginRequiredMixin, View):
  template_name = 'shopping_tab/add_to_tab_modal_result.html'

  def post(self, request, tab_pk, product_id):
    tab = get_object_or_404(ShopingTab, pk=tab_pk, user=request.user)
    product = get_object_or_404(MainProduct, pk=product_id)
    alternate_product_id = request.POST.get('alternate_product_id')
    if alternate_product_id:
      alternate_product = get_object_or_404(
        AlternateProduct,
        pk=alternate_product_id,
        shoping_tabs=tab,
      )
      already_linked = alternate_product.main_product_id == product.pk
      if not already_linked:
        (tab.products
         .filter(main_product=product)
         .exclude(pk=alternate_product.pk)
         .update(main_product=None))
        alternate_product.main_product = product
        alternate_product.save(update_fields=['main_product'])
        status = 'success'
        message_text = (
          f'Товар связан с «{alternate_product.name}» в корзине «{tab.name}».')
      else:
        status = 'info'
        message_text = 'Выбранный товар уже связан с этой позицией корзины.'
    else:
      if tab.products.filter(main_product=product).exists():
        status = 'info'
        message_text = 'Товар уже связан с выбранной корзиной.'
      else:
        alternate_product, created = AlternateProduct.objects.get_or_create(
          name=product.name,
          main_product=product,
        )
        tab.products.add(alternate_product)
        status = 'success'
        if created:
          message_text = f'Товар добавлен в корзину «{tab.name}».'
        else:
          message_text = f'Товар привязан к корзине «{tab.name}».'
    context = {
      'tab': tab,
      'product': product,
      'status': status,
      'message': message_text,
    }
    return render(request, self.template_name, context)


class InstructionsView(LoginRequiredMixin, TemplateView):
    template_name = 'main/instructions.html'
