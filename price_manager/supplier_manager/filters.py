from django_filters import FilterSet

from supplier_manager.models import SupplierProduct


class SupplierProductFilter(FilterSet):
    class Meta:
        model = SupplierProduct
        fields = ['name']
