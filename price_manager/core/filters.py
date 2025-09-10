import django_filters as filters
from .models import *

class MainProductFilter(filters.FilterSet):
  search = filters.CharFilter(method='search_method', label='Поиск')
  basic_price = filters.RangeFilter()
  updated_at = filters.DateRangeFilter(field_name='updated_at')
  category = filters.CharFilter('category__name', lookup_expr='icontains', label='Категория')
  class Meta:
    model = MainProduct
    fields = ['search', 'supplier', 'category', 'available', 'basic_price', 'm_price']
  def search_method(self, queryset, name, value):
    query = SearchQuery(value, search_type="websearch")  # or "websearch" or "plain"
    rank  = SearchRank("search_vector", query)

    queryset = queryset.annotate(rank=rank)

    for bit in value.split(' '):
      query = SearchQuery(bit, search_type="websearch")
      queryset = queryset.filter(search_vector=query)      # uses GIN index
    
    return queryset.order_by("-rank")
  
class SupplierProductFilter(filters.FilterSet):
  class Meta:
    model = SupplierProduct
    fields = ['name']
