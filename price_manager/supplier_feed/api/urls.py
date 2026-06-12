from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    FeedColumnMappingViewSet,
    FeedMappingViewSet,
    FeedMarkupRuleViewSet,
    FeedMarkupSetViewSet,
    SupplierFeedViewSet,
    SupplierLinkViewSet,
)

app_name = 'supplier_feed_api'

router = DefaultRouter()
router.register(r'mappings', FeedMappingViewSet, basename='feedmapping')
router.register(r'feeds', SupplierFeedViewSet, basename='supplierfeed')
router.register(r'links', SupplierLinkViewSet, basename='supplierlink')
router.register(r'markup-sets', FeedMarkupSetViewSet, basename='feedmarkupset')
router.register(r'markup-rules', FeedMarkupRuleViewSet, basename='feedmarkuprule')
router.register(r'column-mappings', FeedColumnMappingViewSet, basename='feedcolumnmapping')

urlpatterns = [
    path('', include(router.urls)),
]
