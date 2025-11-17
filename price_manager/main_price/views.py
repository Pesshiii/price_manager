from collections import OrderedDict, defaultdict
from typing import Iterable

from dal import autocomplete
from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.postgres.search import SearchVector
from django.db.models import Value
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, TemplateView, UpdateView, View
from django_filters.views import FilterView
from django_tables2 import RequestConfig, SingleTableMixin

from main_price.filters import MainProductFilter
from main_price.forms import MainProductForm, ManufacturerDictForm
from main_price.models import Category, MainProduct, Manufacturer, ManufacturerDict
from main_price.tables import (
    MainProductListTable,
    ManufacturerDictListTable,
    ManufacturerListTable,
)
from price_manager_app.models import PriceManager
from price_manager_app.services import apply_price_manager
from supplier_manager.models import Discount, Supplier, SupplierProduct


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


class CategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Category.objects.all()
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs


def build_category_tree(categories: Iterable[Category]):
    children_map = defaultdict(list)
    for category in categories:
        children_map[category.parent_id].append(category)
    for siblings in children_map.values():
        siblings.sort(key=lambda item: item.name.lower())

    def build_nodes(parent_id):
        nodes = []
        for category in children_map.get(parent_id, []):
            nodes.append({'category': category, 'children': build_nodes(category.id)})
        return nodes

    return build_nodes(None)


def _collect_int_values(values):
    result = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _expand_category_ids_with_ancestors(category_ids):
    expanded_ids = set(category_ids)
    to_process = {category_id for category_id in expanded_ids if category_id is not None}
    while to_process:
        parents = set(
            Category.objects.filter(id__in=to_process).values_list('parent_id', flat=True)
        )
        parents.discard(None)
        new_ids = parents - expanded_ids
        if not new_ids:
            break
        expanded_ids.update(new_ids)
        to_process = new_ids
    expanded_ids.discard(None)
    return expanded_ids


def _get_search_filtered_queryset(request):
    filter_data = request.GET.copy()
    for field in ('category', 'supplier', 'manufacturer'):
        filter_data.pop(field, None)
    filter_data.pop('page', None)
    filterset = MainProductFilter(data=filter_data, queryset=MainProduct.objects.all())
    return filterset.qs


def get_main_filter_context(request):
    filterset = MainProductFilter(data=request.GET or None, queryset=MainProduct.objects.all())
    filter_form = filterset.form
    queryset = _get_search_filtered_queryset(request)

    selected_supplier_ids = _collect_int_values(request.GET.getlist('supplier'))
    selected_manufacturer_ids = _collect_int_values(request.GET.getlist('manufacturer'))
    selected_category_ids = _collect_int_values(request.GET.getlist('category'))

    supplier_ids = set(queryset.values_list('supplier_id', flat=True))
    supplier_ids.discard(None)
    supplier_ids.update(selected_supplier_ids)

    manufacturer_ids = set(queryset.values_list('manufacturer_id', flat=True))
    manufacturer_ids.discard(None)
    manufacturer_ids.update(selected_manufacturer_ids)

    category_ids = set(queryset.values_list('category_id', flat=True))
    category_ids.discard(None)
    category_ids.update(selected_category_ids)
    category_ids = _expand_category_ids_with_ancestors(category_ids)

    supplier_queryset = (
        Supplier.objects.filter(id__in=supplier_ids).order_by('name') if supplier_ids else Supplier.objects.none()
    )
    manufacturer_queryset = (
        Manufacturer.objects.filter(id__in=manufacturer_ids).order_by('name')
        if manufacturer_ids
        else Manufacturer.objects.none()
    )
    category_queryset = (
        Category.objects.filter(id__in=category_ids).select_related('parent')
        if category_ids
        else Category.objects.none()
    )

    filter_form.fields['supplier'].queryset = supplier_queryset
    filter_form.fields['manufacturer'].queryset = manufacturer_queryset
    filter_form.fields['category'].queryset = category_queryset

    available_suppliers = list(supplier_queryset)
    available_manufacturers = list(manufacturer_queryset)
    selected_categories = {str(value) for value in request.GET.getlist('category') if value}
    category_tree = build_category_tree(list(category_queryset))

    return {
        'filter_form': filter_form,
        'category_tree': category_tree,
        'selected_categories': selected_categories,
        'available_suppliers': available_suppliers,
        'available_manufacturers': available_manufacturers,
    }


class MainPage(SingleTableMixin, FilterView):
    model = MainProduct
    filterset_class = MainProductFilter
    table_class = MainProductListTable
    template_name = 'main/main.html'
    table_pagination = False

    def get_table(self, **kwargs):
        return super().get_table(**kwargs, request=self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filter_context = get_main_filter_context(self.request)
        context.update(filter_context)
        filterset = context.get('filter')
        category_tables = []
        if filterset is not None:
            filtered_records = filterset.qs.select_related('category')
            if len(filtered_records) > 10000:
                category_table = self.table_class(filtered_records, request=self.request)
                RequestConfig(self.request).configure(category_table)
                category_tables.append({'category': Category.objects.none(), 'table': category_table})
            else:
                grouped_records = OrderedDict()
                grouped_records[None] = {
                    'category': Category.objects.none(),
                    'records': list(filtered_records.filter(category__isnull=True)),
                }
                for category in Category.objects.all():
                    records = list(filtered_records.filter(category=category))
                    if records:
                        grouped_records[category.pk] = {'category': category, 'records': records}
                sorted_groups = sorted(
                    grouped_records.values(),
                    key=lambda item: (
                        item['category'] is None,
                        (item['category'].name.lower() if item['category'] else ''),
                    ),
                )
                for group in sorted_groups:
                    category_table = self.table_class(group['records'], request=self.request)
                    RequestConfig(self.request, paginate=False).configure(category_table)
                    category_tables.append({'category': group['category'], 'table': category_table})
        context['category_tables'] = category_tables
        filter_form = filter_context['filter_form']
        dynamic_url = reverse('main-filter-options')
        hx_attrs = {
            'hx-get': dynamic_url,
            'hx-target': '#filters-update-sink',
            'hx-include': '#main-filter-form',
        }
        search_field = filter_form.fields['search']
        search_field.widget.attrs.update(
            {**hx_attrs, 'hx-trigger': 'keyup changed delay:500ms', 'autocomplete': 'off'}
        )
        anti_search_field = filter_form.fields['anti_search']
        anti_search_field.widget.attrs.update(
            {**hx_attrs, 'hx-trigger': 'keyup changed delay:500ms', 'autocomplete': 'off'}
        )
        if 'available' in filter_form.fields:
            filter_form.fields['available'].widget.attrs.update({**hx_attrs, 'hx-trigger': 'change'})
        context['table_update_url'] = reverse('main-table')
        return context


class MainFilterOptionsView(View):
    template_name = 'main/includes/dynamic_filters.html'

    def get(self, request, *args, **kwargs):
        context = get_main_filter_context(request)
        return render(request, self.template_name, context)


class MainTableView(MainPage):
    template_name = 'main/includes/table.html'


class ManufacturerList(SingleTableMixin, TemplateView):
    table_class = ManufacturerListTable
    template_name = 'manufacturer/list.html'

    def get_table_data(self):
        return Manufacturer.objects.all()


class ManufacturerDetail(SingleTableMixin, TemplateView):
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
    model = Manufacturer
    fields = '__all__'
    success_url = '/manufacturer/'
    template_name = 'manufacturer/create.html'


class ManufacturerDictCreate(CreateView):
    model = ManufacturerDict
    form_class = ManufacturerDictForm
    template_name = 'manufacturer/create.html'

    def get_form(self):
        form = super().get_form()
        form.fields['manufacturer'].initial = Manufacturer.objects.get(id=self.kwargs['id'])
        return form

    def get_success_url(self):
        return reverse('manufacturer-detail', kwargs={'id': self.kwargs['id']})


class MainProductUpdate(UpdateView):
    model = MainProduct
    form_class = MainProductForm
    template_name = 'main/product/update.html'
    success_url = '/'
    pk_url_kwarg = 'id'


def sync_main_products(request, **kwargs):
    updated = 0
    errors = 0
    supplier_products = SupplierProduct.objects.select_related('main_product').all()
    mps = []
    has_rrp = Discount.objects.filter(name='Есть РРЦ').first()
    no_rrp = Discount.objects.filter(name='Нет РРЦ').first()
    for sp in supplier_products:
        try:
            if not sp.main_product:
                continue
            change = False
            mp = sp.main_product
            if mp.stock != sp.stock:
                mp.stock = sp.stock
                mp.stock_updated_at = sp.supplier.stock_updated_at
                change = True
            text = mp._build_search_text()
            mp.search_vector = SearchVector(Value(text), config='russian')
            mps.append(mp)
            if not mp.manufacturer and sp.manufacturer:
                mp.manufacturer = sp.manufacturer
                change = True
            if not mp.category and sp.category:
                mp.category = sp.category
                change = True
            if change:
                mps.append(mp)
        except Exception as ex:
            errors += 1
            messages.error(request, f'Ошибка при обновлении {sp}: {ex}')
    updated = MainProduct.objects.bulk_update(
        mps, ['stock', 'stock_updated_at', 'manufacturer', 'category', 'search_vector']
    )
    messages.success(request, f'Остатки обновлены у {updated} товаров, ошибок: {errors}')
    for price_manager in PriceManager.objects.all():
        if has_rrp and price_manager.discounts.contains(has_rrp):
            price_manager.discounts.remove(has_rrp)
            price_manager.has_rrp = True
            price_manager.save()
        if no_rrp and price_manager.discounts.contains(no_rrp):
            price_manager.discounts.remove(no_rrp)
            price_manager.has_rrp = False
            price_manager.save()
        apply_price_manager(price_manager)
    if has_rrp:
        has_rrp.delete()
    if no_rrp:
        no_rrp.delete()
    messages.success(request, 'Наценки применены')
    return redirect('main')
