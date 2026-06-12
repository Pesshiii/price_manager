from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    FeedColumnMappingViewSet,
    FeedMappingViewSet,
    SupplierFeedViewSet,
    SupplierLinkViewSet,
)

app_name = 'supplier_feed_api'

router = DefaultRouter()
router.register(r'mappings', FeedMappingViewSet, basename='feedmapping')
router.register(r'feeds', SupplierFeedViewSet, basename='supplierfeed')
router.register(r'links', SupplierLinkViewSet, basename='supplierlink')

urlpatterns = [
    path('', include(router.urls)),
    path(
        'mappings/<int:mapping_pk>/column-mappings/',
        FeedColumnMappingViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='column-mapping-list',
    ),
    path(
        'mappings/<int:mapping_pk>/column-mappings/<int:pk>/',
        FeedColumnMappingViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}),
        name='column-mapping-detail',
    ),
]
