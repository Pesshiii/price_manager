from django.urls import path
from django.views.generic import RedirectView

from .views import *
from product_price_manager import views as ppm_views

urlpatterns = [

    # Старая главная удалена (Phase 2b). Адрес живёт в закладках и в истории
    # браузеров, поэтому не 404, а постоянный переход на товарную страницу.
    # Параметры запроса не переносятся: фильтры старой главной (categories по
    # supplier_manager.Category, manufacturer) на /products/ не значат ничего.
    path('', RedirectView.as_view(pattern_name='products', permanent=True), name='mainproducts'),

    path('create', MainProductCreate.as_view(), name='mainproduct-create'),
    path('create/categories', MainProductCreateCategoryTree.as_view(), name='mainproduct-create-categories'),

    path('<int:pk>/update', MainProductUpdate.as_view(), name='main-product-update'),
    path('sync', sync_main_products, name='mainproducts-sync'),
    path('<int:pk>/info', MainProductInfo.as_view(), name='mainproduct-info'),
    path('<int:pk>/update', MainProductUpdate.as_view(), name='mainproduct-update'),
    path('<int:pk>/resolve', ResolveMainproduct.as_view(), name='mainproduct-resolve'),
    path('<int:pk>/detail', MainProductDetail.as_view(), name='mainproduct-detail'),
    path('<int:pk>/pricetags', ppm_views.PriceTagList.as_view(), name='pricetag-list'),
    path('<int:pk>/logs', MainProductLogList.as_view(), name='mainproductlog-list'),

]