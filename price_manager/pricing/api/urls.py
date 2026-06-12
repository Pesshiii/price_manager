from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PriceTypeViewSet, PricingRuleViewSet, ProductPriceViewSet, StockViewSet

app_name = 'pricing_api'

router = DefaultRouter()
router.register(r'price-types', PriceTypeViewSet, basename='price-type')
router.register(r'rules', PricingRuleViewSet, basename='pricing-rule')
router.register(r'prices', ProductPriceViewSet, basename='product-price')
router.register(r'stock', StockViewSet, basename='stock')

urlpatterns = [path('', include(router.urls))]
