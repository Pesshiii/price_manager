from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PriceTypeViewSet, PricingRuleViewSet

app_name = 'pricing_api'

router = DefaultRouter()
router.register(r'price-types', PriceTypeViewSet, basename='price-type')
router.register(r'rules', PricingRuleViewSet, basename='pricing-rule')

urlpatterns = [path('', include(router.urls))]
