from django.urls import path

from .views import *
from product_price_manager import views as ppm_views

urlpatterns = [

    path('', MainPage.as_view(), name='mainproducts'),
    path('table_bycat/<int:category_pk>', MainProductTableView.as_view(), name='mainproduct-table-bycat'),
    path('table_nocat/', MainProductTableView.as_view(), name='mainproduct-table-nocat'),

    path('<int:pk>/update', MainProductUpdate.as_view(), name='main-product-update'),
    path('sync', sync_main_products, name='mainproducts-sync'),
    path('<int:pk>/info', MainProductInfo.as_view(), name='mainproduct-info'),
    path('<int:pk>/update', MainProductUpdate.as_view(), name='mainproduct-update'),
    path('<int:pk>/resolve', ResolveMainproduct.as_view(), name='mainproduct-resolve'),
    path('duplicates/', MainProductDuplicatesView.as_view(), name='mainproduct-duplicates'),
    path('duplicates/select-keep/', MainProductDuplicateSelectionView.as_view(), name='mainproduct-duplicate-select-keep'),
    path('duplicates/table/<int:id>', mainproductdupe, name='mainproduct-duplicate'),
    path('<int:pk>/detail', MainProductDetail.as_view(), name='mainproduct-detail'),
    path('<int:pk>/pricetags', ppm_views.PriceTagList.as_view(), name='pricetag-list'),
    path('<int:pk>/logs', MainProductLogList.as_view(), name='mainproductlog-list'),

]