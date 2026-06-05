from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ProductSnapshotViewSet, SnapshotFieldViewSet, TransformRuleViewSet

app_name = 'transform_api'

router = DefaultRouter()
router.register(r'snapshot-fields', SnapshotFieldViewSet, basename='snapshotfield')
router.register(r'rules', TransformRuleViewSet, basename='transformrule')
router.register(r'snapshots', ProductSnapshotViewSet, basename='productsnapshot')

urlpatterns = [
    path('', include(router.urls)),
]
