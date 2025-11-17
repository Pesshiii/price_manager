from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, UpdateView
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin, SingleTableView

from supplier_manager.filters import SupplierProductFilter
from supplier_manager.models import SUPPLIER_SPECIFIABLE_FIELDS, Supplier, SupplierProduct
from supplier_manager.tables import (
    CurrencyListTable,
    SupplierListTable,
    SupplierProductListTable,
)
from supplier_manager.models import Currency


class SupplierList(SingleTableView):
    model = Supplier
    table_class = SupplierListTable
    template_name = 'supplier/list.html'


class SupplierDetail(SingleTableMixin, FilterView):
    model = SupplierProduct
    table_class = SupplierProductListTable
    filterset_class = SupplierProductFilter
    template_name = 'supplier/detail.html'

    def get_table_data(self):
        return super().get_table_data().filter(supplier=self.kwargs.get('id'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['supplier'] = Supplier.objects.get(id=self.kwargs.get('id'))
        return context


class SupplierCreate(CreateView):
    model = Supplier
    fields = SUPPLIER_SPECIFIABLE_FIELDS
    success_url = '/supplier'
    template_name = 'supplier/create.html'


class SupplierUpdate(UpdateView):
    model = Supplier
    fields = SUPPLIER_SPECIFIABLE_FIELDS
    success_url = '/supplier'
    template_name = 'supplier/update.html'
    pk_url_kwarg = 'id'


class SupplierDelete(DeleteView):
    model = Supplier
    success_url = '/supplier/'
    pk_url_kwarg = 'id'


def delete_supplier_product(request, **kwargs):
    product = SupplierProduct.objects.get(id=kwargs['id'])
    supplier_id = product.supplier.id
    product.delete()
    return redirect('supplier-detail', id=supplier_id)


class CurrencyList(SingleTableView):
    model = Currency
    table_class = CurrencyListTable
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
