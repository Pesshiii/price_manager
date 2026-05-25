from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import FeedMappingViewSet, SupplierFeedViewSet, SupplierLinkViewSet

app_name = 'supplier_feed_api'

router = DefaultRouter()
router.register(r'mappings', FeedMappingViewSet, basename='feedmapping')
router.register(r'feeds', SupplierFeedViewSet, basename='supplierfeed')
router.register(r'links', SupplierLinkViewSet, basename='supplierlink')

urlpatterns = [
    path('', include(router.urls)),
]
