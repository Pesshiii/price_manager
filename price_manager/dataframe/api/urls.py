from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DataframeViewSet, PreviewView, RegistryView, UploadSessionView

app_name = 'dataframe_api'

router = DefaultRouter()
router.register(r'pipelines', DataframeViewSet, basename='pipeline')

urlpatterns = [
    path('registry/', RegistryView.as_view(), name='registry'),
    path('sessions/', UploadSessionView.as_view(), name='session-create'),
    path('sessions/<str:session_id>/', UploadSessionView.as_view(), name='session-detail'),
    path('preview/', PreviewView.as_view(), name='preview'),
    path('', include(router.urls)),
]
