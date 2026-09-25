import django_tables2 as tables
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.html import format_html

from .models import ProductPriceRule, ProductPriceType


def _edit_link(url, label):
    return format_html(
        '<a href="#" class="text-decoration-none" data-bs-toggle="modal" data-bs-target="#modal-container"'
        ' hx-get="{}" hx-target="#modal-container .modal-content" hx-swap="innerHTML">'
        '<i class="bi bi-pencil-square me-1"></i>{}</a>', url, label)


class ProductPriceTypeTable(tables.Table):
    prices_count = tables.Column(verbose_name='Товаров с ценой', attrs={'td': {'class': 'text-end'}})

    class Meta:
        model = ProductPriceType
        fields = ['name', 'pim_field', 'show_on_page', 'sorting', 'prices_count']
        orderable = False
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-sm table-hover align-middle mb-0'}

    def render_name(self, record):
        return _edit_link(reverse('product-price-type-update', kwargs={'pk': record.pk}), record.name)

    def render_pim_field(self, value):
        return value or '—'

    def render_show_on_page(self, value):
        return format_html('<i class="bi bi-{}"></i>', 'check-lg' if value else 'dash')


class ProductPriceRuleTable(tables.Table):
    formula = tables.Column(verbose_name='Расчёт', empty_values=())
    scope = tables.Column(verbose_name='Какие товары', empty_values=())
    period = tables.Column(verbose_name='Период', empty_values=())
    prices_count = tables.Column(verbose_name='Товаров', attrs={'td': {'class': 'text-end'}})

    class Meta:
        model = ProductPriceRule
        fields = ['name', 'price_type', 'formula', 'scope', 'period', 'priority', 'is_active', 'prices_count']
        sequence = fields
        orderable = False
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-sm table-hover align-middle mb-0'}
        row_attrs = {'class': lambda record: '' if record.is_active else 'text-body-tertiary'}

    def render_name(self, record):
        return _edit_link(reverse('product-price-rule-update', kwargs={'pk': record.pk}), record.name)

    def render_formula(self, record):
        return record.formula_label()

    def render_scope(self, record):
        return record.scope_label()

    def render_period(self, record):
        if not record.date_from and not record.date_to:
            return 'Бессрочно'
        low = date_format(record.date_from, 'SHORT_DATE_FORMAT') if record.date_from else '…'
        high = date_format(record.date_to, 'SHORT_DATE_FORMAT') if record.date_to else '…'
        return f'{low} – {high}'

    def render_is_active(self, value):
        return format_html('<i class="bi bi-{}"></i>', 'check-lg' if value else 'dash')
