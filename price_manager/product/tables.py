import django_tables2 as tables

from core.tables import HTMXMixin, SelectableColumnsMixin

from .models import Product


class Table(SelectableColumnsMixin, HTMXMixin, tables.Table):
    class Meta:
        model=Product
        fields='__all__'