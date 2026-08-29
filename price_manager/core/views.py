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
from django.http import HttpResponse
from django_htmx.http import reswap, trigger_client_event


# Импорты моделей, функций, форм, таблиц
from core.models import *
from file_manager.models import FileModel
from .utils import *
from .forms import *
from .tables import *
from .filters import *

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation
import pandas as pd
import re
import math

def toast_messages(request):
    storage = messages.get_messages(request)
    if len(storage) == 0:
        response = HttpResponse()
        return reswap(response, "none")
    response = render(request, "core/partials/toast_messages.html")
    return trigger_client_event(response, "toasts:initialize", after="swap")


class PersistentNotificationDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(PersistentNotification, pk=pk, user=request.user)
        notification.delete()
        remaining = (
            PersistentNotification.objects
            .filter(user=request.user)
            .order_by('-created_at')[:30]
        )
        return render(
            request,
            "core/partials/notifications_delete_response.html",
            {"persistent_notifications": remaining},
        )


class PersistentNotificationsPanelView(LoginRequiredMixin, View):
    def get(self, request):
        notifications = (
            PersistentNotification.objects
            .filter(user=request.user)
            .order_by('-created_at')[:30]
        )
        return render(
            request,
            "core/partials/notifications_panel.html",
            {"persistent_notifications": notifications},
        )

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
    form_class = ShoppingTabCreateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get('form')
        context['form'] = form if form is not None else self.form_class()
        context['tabs'] = (
        ShoppingTab.objects
            .filter(user=self.request.user)
            .annotate(item_count=Count('items', distinct=True))
            .order_by('name')
        )
        context['items'] = {tab.name: [item for item in tab.items.all()] for tab in context['tabs']}
        return context

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            if ShoppingTab.objects.filter(user=request.user, name=name).exists():
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
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        tab.delete()
        messages.success(request, 'Корзина удалена.')
        return redirect('shopping-tab-list')


def _get_shopping_tab_items(tab):
    return (
        tab.items
        .select_related('confirmed_product')
        .prefetch_related('products')
        .all()
    )


class ShoppingTabDetailView(LoginRequiredMixin, View):
    template_name = 'shopping_tab/detail.html'
    form_class = ShoppingTabUpdateForm

    def get_context_data(self, tab, form=None):
        return {
            'tab': tab,
            'form': form if form is not None else self.form_class(instance=tab),
            'items': _get_shopping_tab_items(tab),
        }

    def get(self, request, pk):
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        return render(request, self.template_name, self.get_context_data(tab))

    def post(self, request, pk):
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        form = self.form_class(request.POST, instance=tab)
        if form.is_valid():
            form.save()
            messages.success(request, 'Корзина обновлена.')
            return redirect('shopping-tab-detail', pk=tab.pk)
        return render(request, self.template_name, self.get_context_data(tab, form=form))


class ShoppingTabAddItemView(LoginRequiredMixin, View):
    template_name = 'shopping_tab/partials/add_item_form.html'

    def get(self, request, pk):
        if not request.htmx:
            return redirect('shopping-tab-detail', pk=pk)
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        return render(request, self.template_name, {'tab': tab})

    def post(self, request, pk):
        if not request.htmx:
            return redirect('shopping-tab-detail', pk=pk)
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        search_query = request.POST.get('search_query', '').strip()
        context = {'tab': tab, 'search_query': search_query}
        if not search_query:
            context['error'] = 'Введите название или артикул товара.'
            return render(request, self.template_name, context)
        item = CartItem.objects.create(user=request.user, search_query=search_query)
        tab.items.add(item)
        context['search_query'] = ''
        context['item_added'] = True
        context['items'] = _get_shopping_tab_items(tab)
        return render(request, self.template_name, context)


class InstructionsView(LoginRequiredMixin, TemplateView):
    template_name = 'main/instructions.html'


def mainpage(request):
    return redirect('mainproducts')