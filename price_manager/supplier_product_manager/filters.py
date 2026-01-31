from django_filters import FilterSet
from .models import SupplierProduct

class SupplierProductFilter(FilterSet):
  class Meta:
    model = SupplierProduct
    fields = ['name']
