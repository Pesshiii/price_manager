from django.template.loader import render_to_string
import django_tables2 as tables

from common.utils import get_field_details
from main_price.models import (
    Category,
    MainProduct,
    Manufacturer,
    ManufacturerDict,
    MP_TABLE_FIELDS,
)


class ManufacturerListTable(tables.Table):
    name = tables.LinkColumn('manufacturer-detail', args=[tables.A('pk')])

    class Meta:
        model = Manufacturer
        fields = [field for field, value in get_field_details(model).items() if '_ptr' not in field]
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}


class ManufacturerDictListTable(tables.Table):
    class Meta:
        model = ManufacturerDict
        fields = [field for field, value in get_field_details(model).items() if not value['is_relation']]
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}


class CategoryListTable(tables.Table):
    class Meta:
        model = Category
        fields = ['parent', 'name']
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}


class MainProductListTable(tables.Table):
    actions = tables.Column(empty_values=(), orderable=False, verbose_name='')

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super().__init__(*args, **kwargs)

    class Meta:
        model = MainProduct
        fields = ['actions', *MP_TABLE_FIELDS]
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'clickable-rows table table-auto table-stripped table-hover'}

    def render_actions(self, record):
        return render_to_string('main/product/actions.html', {'record': record, 'request': self.request}, request=self.request)

    def render_name(self, record):
        return render_to_string('main/product/card.html', {'record': record})
