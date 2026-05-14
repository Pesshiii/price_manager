from django.urls import path, re_path

from .views import (
    ProductListView,
    ProductDetailView,
    ProductImportSelectView,
    ProductImportView,
    ProductImportExecuteView,
)

app_name = 'product'

urlpatterns = [
    path('', ProductListView.as_view(), name='product-list'),
    path('import/', ProductImportSelectView.as_view(), name='product-import-select'),
    path('import/<int:pk>/', ProductImportView.as_view(), name='product-import'),
    path('import/<int:pk>/execute/', ProductImportExecuteView.as_view(), name='product-import-execute'),
    re_path(r'^(?P<slug>[-\w]+)/$', ProductDetailView.as_view(), name='product-detail'),
]
