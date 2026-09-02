from django.db.models import Q
from rest_framework import viewsets

from pricing.models import PriceType, PricingRule
from .pagination import StandardPagination
from .serializers import PriceTypeSerializer, PricingRuleSerializer


class PriceTypeViewSet(viewsets.ModelViewSet):
    serializer_class = PriceTypeSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = PriceType.objects.all()
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(label__icontains=search))
        return qs


class PricingRuleViewSet(viewsets.ModelViewSet):
    serializer_class = PricingRuleSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = PricingRule.objects.select_related('supplier', 'source_price_type', 'dest_price_type', 'category')
        supplier = self.request.query_params.get('supplier')
        if supplier:
            try:
                qs = qs.filter(supplier_id=int(supplier))
            except (ValueError, TypeError):
                return qs.none()
        return qs
