from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BrandViewSet,
    CategoryViewSet,
    CharacteristicTypeViewSet,
    ImportCommitView,
    ImportJobView,
    ImportPreviewView,
    ProductViewSet,
)

app_name = 'product_api'

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'brands', BrandViewSet, basename='brand')
router.register(r'characteristic-types', CharacteristicTypeViewSet, basename='characteristic-type')
router.register(r'products', ProductViewSet, basename='product')

urlpatterns = [
    path('import/preview/', ImportPreviewView.as_view(), name='import-preview'),
    path('import/commit/', ImportCommitView.as_view(), name='import-commit'),
    path('import/jobs/<uuid:job_id>/', ImportJobView.as_view(), name='import-job'),
    path('', include(router.urls)),
]
