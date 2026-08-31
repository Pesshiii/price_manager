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
from django.http import HttpResponse, FileResponse, Http404
from django_htmx.http import reswap, trigger_client_event


# Импорты моделей, функций, форм, таблиц
from core.models import *
from file_manager.models import FileModel
from main_product_manager.models import MainProduct
from main_product_manager.filters import MainProductFilter
from .tasks import update_cart_items_task, export_shopping_tab_task
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
    return order_cart_items(
        tab.items
        .select_related('confirmed_product', 'confirmed_product__supplier')
        .prefetch_related('products')
    )


def _shopping_tab_summary(tab):
    """Позиции заявки вместе со сводкой: сколько подтверждено и на какую сумму."""
    items = list(_get_shopping_tab_items(tab))
    confirmed = [item for item in items if item.confirmed_product_id]
    return {
        'items': items,
        'items_total': len(items),
        'items_confirmed': len(confirmed),
        'items_pending': len(items) - len(confirmed),
        'items_sum': sum((item.line_total or 0) for item in items),
        'progress': round(len(confirmed) / len(items) * 100) if items else 0,
        # Здесь, а не в контексте страницы: сводка перерисовывается и по htmx.
        'latest_export': tab.exports.exclude(file='').exclude(file__isnull=True).first(),
    }


class ShoppingTabDetailView(LoginRequiredMixin, View):
    template_name = 'shopping_tab/detail.html'
    form_class = ShoppingTabUpdateForm

    def get_context_data(self, tab, form=None):
        return {
            'tab': tab,
            'form': form if form is not None else self.form_class(instance=tab),
            **_shopping_tab_summary(tab),
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


class ShoppingTabExportView(LoginRequiredMixin, View):
    """Ставит выгрузку заявки в очередь."""

    def post(self, request, pk):
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        export_shopping_tab_task.delay(shopping_tab_id=tab.pk, user_id=request.user.pk)
        messages.info(request, 'Экспорт запущен. Ссылка на файл придёт в уведомлениях.')
        return redirect('shopping-tab-detail', pk=tab.pk)


class ShoppingTabExportDownloadView(LoginRequiredMixin, View):
    """Отдаёт готовый файл выгрузки владельцу."""

    def get(self, request, pk):
        export = get_object_or_404(ShoppingTabExport, pk=pk, user=request.user)
        if not export.file:
            raise Http404('Файл выгрузки не найден')
        return FileResponse(
            export.file.open('rb'),
            as_attachment=True,
            filename=f'{export.tab.name}.xlsx',
        )


IMPORT_PREVIEW_ROWS = 5
IMPORT_UPLOAD_TEMPLATE = 'shopping_tab/partials/import_upload.html'
IMPORT_MAPPING_TEMPLATE = 'shopping_tab/partials/import_mapping.html'


def _guess_column(columns, keywords):
    for column in columns:
        lowered = str(column).lower()
        if any(keyword in lowered for keyword in keywords):
            return column
    return None


def _render_import_mapping(request, tab, query_column=None, quantity_column=None, guess=False):
    """Шаг сопоставления колонок вместе с разбором первых строк."""
    try:
        df = read_shopping_tab_dataframe(tab)
    except Exception as exc:
        return render(request, IMPORT_UPLOAD_TEMPLATE, {
            'tab': tab,
            'error': f'Не удалось прочитать файл: {exc}',
        })

    columns = [str(column) for column in df.columns]
    if not columns:
        return render(request, IMPORT_UPLOAD_TEMPLATE, {
            'tab': tab,
            'error': 'В файле не найдено ни одной колонки.',
        })

    if guess:
        query_column = _guess_column(columns, ('наимен', 'назв', 'товар', 'запрос', 'name')) or columns[0]
        quantity_column = _guess_column(columns, ('кол', 'колич', 'quantity', 'qty'))
    else:
        if query_column not in columns:
            query_column = columns[0]
        # Пустое значение — осознанный выбор «не указана», а не повод угадывать заново.
        if quantity_column not in columns:
            quantity_column = None

    rows = parse_cart_item_rows(df, query_column, quantity_column)
    return render(request, IMPORT_MAPPING_TEMPLATE, {
        'tab': tab,
        'columns': columns,
        'query_column': query_column,
        'quantity_column': quantity_column,
        'preview': rows[:IMPORT_PREVIEW_ROWS],
        'total_rows': len(rows),
        'skipped_rows': len(df.index) - len(rows),
    })


class ShoppingTabImportView(LoginRequiredMixin, View):
    """Шаг 1: загрузка файла. Файл сохраняется в ShoppingTab.file и читается дальше оттуда."""

    def get(self, request, pk):
        if not request.htmx:
            return redirect('shopping-tab-detail', pk=pk)
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        return render(request, IMPORT_UPLOAD_TEMPLATE, {'tab': tab})

    def post(self, request, pk):
        if not request.htmx:
            return redirect('shopping-tab-detail', pk=pk)
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        uploaded = request.FILES.get('file')
        if not uploaded:
            return render(request, IMPORT_UPLOAD_TEMPLATE, {'tab': tab, 'error': 'Выберите файл.'})
        if not uploaded.name.lower().endswith(CART_IMPORT_EXTENSIONS):
            return render(request, IMPORT_UPLOAD_TEMPLATE, {
                'tab': tab,
                'error': 'Поддерживаются только файлы .xlsx, .xls и .csv.',
            })
        tab.file = uploaded
        tab.save(update_fields=['file'])
        return _render_import_mapping(request, tab, guess=True)


class ShoppingTabImportPreviewView(LoginRequiredMixin, View):
    """Шаг 2: пересборка предпросмотра при смене колонок."""

    def post(self, request, pk):
        if not request.htmx:
            return redirect('shopping-tab-detail', pk=pk)
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        return _render_import_mapping(
            request,
            tab,
            query_column=request.POST.get('query_column'),
            quantity_column=request.POST.get('quantity_column'),
        )


class ShoppingTabImportRunView(LoginRequiredMixin, View):
    """Шаг 3: запуск фонового импорта."""
    template_name = 'shopping_tab/partials/import_started.html'

    def post(self, request, pk):
        if not request.htmx:
            return redirect('shopping-tab-detail', pk=pk)
        tab = get_object_or_404(ShoppingTab, pk=pk, user=request.user)
        query_column = request.POST.get('query_column')
        quantity_column = request.POST.get('quantity_column') or None
        try:
            columns = [str(column) for column in read_shopping_tab_dataframe(tab).columns]
        except Exception as exc:
            return render(request, IMPORT_UPLOAD_TEMPLATE, {
                'tab': tab,
                'error': f'Не удалось прочитать файл: {exc}',
            })
        if query_column not in columns:
            return _render_import_mapping(request, tab, query_column, quantity_column)
        if quantity_column not in columns:
            quantity_column = None

        update_cart_items_task.delay(
            shopping_tab_id=tab.pk,
            query_column=query_column,
            quantity_column=quantity_column,
            user_id=request.user.pk,
        )
        return render(request, self.template_name, {'tab': tab})


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
        quantity_raw = request.POST.get('quantity', '').strip()
        context = {'tab': tab, 'search_query': search_query, 'quantity': quantity_raw}
        if not search_query:
            context['error'] = 'Введите название или артикул товара.'
            return render(request, self.template_name, context)
        try:
            quantity = int(quantity_raw) if quantity_raw else 1
            if quantity < 1:
                raise ValueError
        except ValueError:
            context['error'] = 'Количество должно быть целым числом не меньше 1.'
            return render(request, self.template_name, context)
        item = CartItem.objects.create(user=request.user, search_query=search_query, quantity=quantity)
        item.products.set(find_main_products(search_query))
        tab.items.add(item)
        context['search_query'] = ''
        context['quantity'] = 1
        context['item_added'] = True
        context.update(_shopping_tab_summary(tab))
        return render(request, self.template_name, context)


class CartItemDetailView(LoginRequiredMixin, DetailView):
    model = CartItem
    template_name = 'shopping_tab/item_detail.html'
    context_object_name = 'item'

    def get_queryset(self):
        return (
            CartItem.objects
            .filter(user=self.request.user)
            .select_related('confirmed_product')
            .prefetch_related('products')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tab'] = self.object.shopping_tabs.filter(user=self.request.user).first()
        return context


class CartItemQuickAddView(LoginRequiredMixin, View):
    """Добавление товара из главного прайса в заявку одной модалкой.

    Запрос подставляется из названия товара, но остаётся редактируемым: по нему
    подбираются остальные кандидаты, а сам выбранный товар сразу подтверждается.
    """
    template_name = 'shopping_tab/partials/quick_add_modal.html'
    result_template_name = 'shopping_tab/partials/quick_add_result.html'

    def get_tabs(self):
        return ShoppingTab.objects.filter(user=self.request.user).order_by('-open', 'name')

    def get(self, request, product_pk):
        if not request.htmx:
            return redirect('mainproducts')
        product = get_object_or_404(MainProduct, pk=product_pk)
        return render(request, self.template_name, {
            'product': product,
            'tabs': self.get_tabs(),
            'search_query': product.name,
            'quantity': 1,
        })

    def post(self, request, product_pk):
        if not request.htmx:
            return redirect('mainproducts')
        product = get_object_or_404(MainProduct, pk=product_pk)
        tabs = self.get_tabs()
        search_query = (request.POST.get('search_query') or '').strip()
        quantity_raw = (request.POST.get('quantity') or '').strip()
        selected_tab = request.POST.get('tab') or ''
        context = {
            'product': product,
            'tabs': tabs,
            'search_query': search_query,
            'quantity': quantity_raw or 1,
            'selected_tab': selected_tab,
        }

        tab = tabs.filter(pk=selected_tab).first() if selected_tab.isdigit() else None
        if tab is None:
            context['error'] = 'Выберите заявку.'
            return render(request, self.template_name, context)
        if not search_query:
            context['error'] = 'Введите поисковый запрос.'
            return render(request, self.template_name, context)
        try:
            quantity = int(quantity_raw) if quantity_raw else 1
            if quantity < 1:
                raise ValueError
        except ValueError:
            context['error'] = 'Количество должно быть целым числом не меньше 1.'
            return render(request, self.template_name, context)

        item = CartItem.objects.create(
            user=request.user,
            search_query=search_query,
            quantity=quantity,
        )
        candidates = find_main_products(search_query)
        if product not in candidates:
            candidates.append(product)
        item.products.set(candidates)
        item.confirmed_product = product
        item.save(update_fields=['confirmed_product'])
        tab.items.add(item)
        return render(request, self.result_template_name, {
            'product': product,
            'tab': tab,
            'item': item,
        })


class CartItemConfirmProductView(LoginRequiredMixin, View):
    """Подтверждает товар для позиции заявки."""
    template_name = 'shopping_tab/partials/item_confirm_response.html'

    def post(self, request, pk, product_pk):
        if not request.htmx:
            return redirect('cart-item-detail', pk=pk)
        item = get_object_or_404(CartItem, pk=pk, user=request.user)
        product = get_object_or_404(MainProduct, pk=product_pk)
        # Подтверждать можно и товар, которого ещё нет в подходящих — тогда добавляем его.
        if not item.products.filter(pk=product.pk).exists():
            item.products.add(product)
        item.confirmed_product = product
        item.save(update_fields=['confirmed_product'])
        return render(request, self.template_name, {'item': item})


class CartItemUnconfirmView(LoginRequiredMixin, View):
    """Снимает подтверждение товара, оставляя его в списке подходящих."""
    template_name = 'shopping_tab/partials/item_confirm_response.html'

    def post(self, request, pk):
        if not request.htmx:
            return redirect('cart-item-detail', pk=pk)
        item = get_object_or_404(CartItem, pk=pk, user=request.user)
        item.confirmed_product = None
        item.save(update_fields=['confirmed_product'])
        return render(request, self.template_name, {'item': item})


class CartItemRemoveProductView(LoginRequiredMixin, View):
    """Убирает товар из подходящих. Подтверждение с него снимается заодно."""
    template_name = 'shopping_tab/partials/item_confirm_response.html'

    def post(self, request, pk, product_pk):
        if not request.htmx:
            return redirect('cart-item-detail', pk=pk)
        item = get_object_or_404(CartItem, pk=pk, user=request.user)
        product = get_object_or_404(MainProduct, pk=product_pk)
        item.products.remove(product)
        # Подтверждённым не может остаться товар, которого больше нет в подходящих.
        if item.confirmed_product_id == product.pk:
            item.confirmed_product = None
            item.save(update_fields=['confirmed_product'])
        return render(request, self.template_name, {'item': item})


class CartItemProductSelectView(LoginRequiredMixin, SingleTableMixin, FilterView):
    """Модалка выбора товаров Главного прайса для элемента корзины.

    Построена по образцу ResolveMainproduct: тот же MainProductFilter и та же
    htmx-таблица с догрузкой страниц, но одной плоской таблицей вместо разбивки
    по категориям — иначе отметки чекбоксов разъехались бы по независимо
    подгружаемым фрагментам.
    """
    model = MainProduct
    filterset_class = MainProductFilter
    table_class = CartItemProductTable
    template_name = 'shopping_tab/partials/product_select_modal.html'

    def get(self, request, *args, **kwargs):
        if not request.htmx:
            return redirect('cart-item-detail', pk=self.kwargs.get('pk'))
        self.item = get_object_or_404(CartItem, pk=self.kwargs.get('pk'), user=request.user)
        return super().get(request, *args, **kwargs)

    def get_template_names(self):
        if self.request.GET.get('page'):
            return [self.template_name + '#table']
        if self.request.GET.get('bound'):
            return [self.template_name + '#tableblock']
        return [self.template_name]

    def _select_url(self):
        return reverse('cart-item-products-select', kwargs={'pk': self.item.pk})

    def get_filterset_kwargs(self, filterset_class):
        kwargs = super().get_filterset_kwargs(filterset_class)
        data = self.request.GET.copy()
        if 'bound' not in data and 'search' not in data:
            data['search'] = self.item.search_query or ''
        # MainProductFilter.config_filters вызывает data.getlist, поэтому нужен QueryDict
        kwargs['data'] = data
        return kwargs

    def get_filterset(self, filterset_class):
        filterset = super().get_filterset(filterset_class)
        helper = filterset.build_helper(url=self._select_url(), hx_target='#cart-item-product-table')
        helper.attrs['hx-push-url'] = 'false'
        return filterset

    def get_table_kwargs(self):
        kwargs = super().get_table_kwargs()
        kwargs['request'] = self.request
        kwargs['url'] = self._select_url()
        kwargs['item'] = self.item
        kwargs['existing_ids'] = set(self.item.products.values_list('pk', flat=True))
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['item'] = self.item
        return context


class CartItemAddProductsView(LoginRequiredMixin, View):
    template_name = 'shopping_tab/partials/products_added.html'

    def post(self, request, pk):
        if not request.htmx:
            return redirect('cart-item-detail', pk=pk)
        item = get_object_or_404(CartItem, pk=pk, user=request.user)
        # Клик по названию шлёт single_product_id: htmx подмешивает в запрос поля
        # окружающей формы, поэтому отмеченные чекбоксы нужно явно проигнорировать.
        single_product_id = request.POST.get('single_product_id')
        raw_ids = [single_product_id] if single_product_id else request.POST.getlist('product_ids')
        ids = [raw_id for raw_id in raw_ids if str(raw_id).isdigit()]
        existing_ids = set(item.products.values_list('pk', flat=True))
        added_products = [
            product for product in MainProduct.objects.filter(pk__in=ids)
            if product.pk not in existing_ids
        ]
        if added_products:
            item.products.add(*added_products)
        return render(request, self.template_name, {
            'item': item,
            'added_products': added_products,
        })


class InstructionsView(LoginRequiredMixin, TemplateView):
    template_name = 'main/instructions.html'


def mainpage(request):
    return redirect('mainproducts')