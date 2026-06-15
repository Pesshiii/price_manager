from django.db.models import Q
from rest_framework import viewsets

from pricing.models import PriceType, PricingRule, ProductPrice, Stock
from .pagination import StandardPagination
from .serializers import PriceTypeSerializer, PricingRuleSerializer, ProductPriceSerializer, StockSerializer


class PriceTypeViewSet(viewsets.ModelViewSet):
    serializer_class = PriceTypeSerializer
    pagination_class = None

    def get_queryset(self):
        qs = PriceType.objects.all()
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(label__icontains=search))
        return qs


class PricingRuleViewSet(viewsets.ModelViewSet):
    serializer_class = PricingRuleSerializer
    pagination_class = None

    def get_queryset(self):
        qs = PricingRule.objects.select_related('supplier', 'source_price_type', 'dest_price_type', 'category')
        supplier = self.request.query_params.get('supplier')
        if supplier:
            try:
                qs = qs.filter(supplier_id=int(supplier))
            except (ValueError, TypeError):
                return qs.none()
        return qs


class ProductPriceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductPriceSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = ProductPrice.objects.select_related('price_type', 'supplier', 'rule')
        product = self.request.query_params.get('product')
        supplier = self.request.query_params.get('supplier')
        price_type = self.request.query_params.get('price_type')
        if product:
            try:
                qs = qs.filter(product_id=int(product))
            except (ValueError, TypeError):
                return qs.none()
        if supplier:
            try:
                qs = qs.filter(supplier_id=int(supplier))
            except (ValueError, TypeError):
                return qs.none()
        if price_type:
            try:
                qs = qs.filter(price_type_id=int(price_type))
            except (ValueError, TypeError):
                return qs.none()
        return qs


class StockViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Stock.objects.select_related('product', 'supplier')
        product = self.request.query_params.get('product')
        supplier = self.request.query_params.get('supplier')
        if product:
            try:
                qs = qs.filter(product_id=int(product))
            except (ValueError, TypeError):
                return qs.none()
        if supplier:
            try:
                qs = qs.filter(supplier_id=int(supplier))
            except (ValueError, TypeError):
                return qs.none()
        return qs
