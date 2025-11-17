from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import format_html
import django_tables2 as tables

from common.utils import get_field_details
from supplier_manager.models import SP_TABLE_FIELDS, Supplier, SupplierProduct, TIME_FREQ


class SupplierListTable(tables.Table):
    actions = tables.TemplateColumn(
        template_name='supplier/actions.html',
        orderable=False,
        verbose_name='Действия',
    )
    name = tables.LinkColumn('supplier-detail', args=[tables.A('pk')])

    class Meta:
        model = Supplier
        fields = ['name', 'price_updated_at', 'stock_updated_at']
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}

    def render_name(self, record):
        now = timezone.now()
        try:
            danger = (
                (now - record.stock_updated_at).days >= TIME_FREQ[record.stock_update_rate]
                or (now - record.price_updated_at).days >= TIME_FREQ[record.price_update_rate]
            )
        except Exception:
            danger = False
        color = 'danger' if danger else 'success'
        return format_html('<span class="status-indicator bg-{} rounded-circle"></span> {}', color, record.name)


class SupplierProductListTable(tables.Table):
    actions = tables.TemplateColumn(
        template_name='supplier/product/actions.html',
        orderable=False,
        verbose_name='Действия',
        attrs={'td': {'class': 'text-right'}},
    )

    class Meta:
        model = SupplierProduct
        fields = SP_TABLE_FIELDS
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}


class SupplierProductPriceManagerTable(tables.Table):
    class Meta:
        model = SupplierProduct
        fields = SP_TABLE_FIELDS
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}


class CurrencyListTable(tables.Table):
    name = tables.LinkColumn('currency-update', args=[tables.A('pk')])

    class Meta:
        from supplier_manager.models import Currency

        model = Currency
        fields = [field for field, value in get_field_details(model).items() if not value['is_relation']]
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}
