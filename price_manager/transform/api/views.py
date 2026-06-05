from rest_framework import mixins, viewsets
from rest_framework.pagination import PageNumberPagination

from ..models import ProductSnapshot, SnapshotField, TransformRule
from .serializers import ProductSnapshotSerializer, SnapshotFieldSerializer, TransformRuleSerializer


class _Pagination(PageNumberPagination):
    page_size = 200
    page_size_query_param = 'page_size'
    max_page_size = 1000


class SnapshotFieldViewSet(viewsets.ModelViewSet):
    queryset = SnapshotField.objects.all()
    serializer_class = SnapshotFieldSerializer
    pagination_class = _Pagination


class TransformRuleViewSet(viewsets.ModelViewSet):
    serializer_class = TransformRuleSerializer
    pagination_class = _Pagination

    def get_queryset(self):
        qs = TransformRule.objects.select_related('feed_mapping', 'target_field')
        feed_mapping = self.request.query_params.get('feed_mapping')
        if feed_mapping is not None:
            qs = qs.filter(feed_mapping_id=feed_mapping)
        return qs


class ProductSnapshotViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ProductSnapshotSerializer
    pagination_class = _Pagination

    def get_queryset(self):
        qs = ProductSnapshot.objects.select_related('product', 'supplier', 'source_feed')
        product = self.request.query_params.get('product')
        supplier = self.request.query_params.get('supplier')
        if product is not None:
            qs = qs.filter(product_id=product)
        if supplier is not None:
            qs = qs.filter(supplier_id=supplier)
        return qs
