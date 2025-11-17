import django_tables2 as tables

from common.utils import get_field_details
from price_manager_app.models import PriceManager


class PriceManagerListTable(tables.Table):
    name = tables.LinkColumn('price-manager-update', args=[tables.A('pk')])

    class Meta:
        model = PriceManager
        fields = [key for key, value in get_field_details(PriceManager).items() if '_ptr' not in key]
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}
