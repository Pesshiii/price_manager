
from django.contrib import admin
from django.urls import path
from core import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', views.AppLoginView.as_view(), name='login'),
    path('accounts/logout/', views.AppLogoutView.as_view(), name='logout'),

    path('', views.MainPage.as_view(), name='main'),
    path('main/filter-options/', views.MainFilterOptionsView.as_view(), name='main-filter-options'),
    path('main/table/', views.MainTableView.as_view(), name='main-table'),
    
    path('supplier/', views.SupplierList.as_view(), name='supplier'),
    path('supplier/<int:id>/', views.SupplierDetail.as_view(), name='supplier-detail'),
    path('supplier/<int:id>/update', views.SupplierUpdate.as_view(), name='supplier-update'),
    path('supplier/<int:id>/delete/', views.SupplierDelete.as_view(), name='supplier-delete'),
    path('supplier/<int:id>/settings/', views.SupplierSettingList.as_view(), name='supplier-settings'),
    path('supplier/create/', views.SupplierCreate.as_view(), name='supplier-create'),
    path('supplier/<int:id>/setting/create/<int:f_id>/', views.SettingCreate.as_view(), name='setting-create'),

    path('setting/<int:id>/', views.SettingDetail.as_view(), name='setting-detail'),
    path('setting/<int:id>/delete', views.SettingDelete.as_view(), name='setting-delete'),
    path('setting/<int:id>/upload/<int:f_id>/', views.SettingUpdate.as_view(), name='setting-update'),
    path('setting/<int:id>/upload/<int:f_id>/upload', views.SettingUpload.as_view(), name='setting-upload'),

    # path('manufacturer/', views.ManufacturerList.as_view(), name='manufacturer'),
    # path('manufacturer/<int:id>/', views.ManufacturerDetail.as_view(), name='manufacturer-detail'),
    # path('manufacturer/<int:id>/add-alt/', views.ManufacturerDictCreate.as_view(), name='manufacturer-dict-create'),
    # path('manufacturer/create/', views.ManufacturerCreate.as_view(), name='manufacturer-create'),
    
    # path('category/', views.CategoryList.as_view(), name='category'),
    # path('category/<int:id>/delete/', views.CategoryDelete.as_view(), name='category-delete'),
    # path('category/sort/', views.CategorySortSupplierProduct.as_view(), name='category-sort'),
    # path('category/create/', views.CategoryCreate.as_view(), name='category-create'),
    path('category/autocomplete',views.CategoryAutocomplete.as_view(),name='category-autocomplete'),
    
    path('currency/', views.CurrencyList.as_view(), name='currency'),
    path('currency/create/', views.CurrencyCreate.as_view(), name='currency-create'),
    path('currency/<int:id>/update', views.CurrencyUpdate.as_view(), name='currency-update'),

    path('price-manager/', views.PriceManagerList.as_view(), name='price-manager'),
    path('price-manager/<int:id>/', views.PriceManagerUpdate.as_view(), name='price-manager-update'),
    path('price-manager/create/', views.PriceManagerCreate.as_view(), name='price-manager-create'),
    path('price-manager/<int:id>/delete', views.PriceManagerDelete.as_view(), name='price-manager-delete'),

    path('supplier-product/<int:id>/delete/', views.delete_supplier_product, name='supplier-product-delete'),

    path('main-product/<int:id>/update', views.MainProductUpdate.as_view(), name='main-product-update'),
    path('main-product/sync/', views.sync_main_products, name='main-product-sync'),
    path('upload/<str:name>/<int:id>/', views.FileUpload.as_view(), name='upload'),

    path('shopping-tabs/', views.ShoppingTabListView.as_view(), name='shopping-tab-list'),
    path('shopping-tabs/<int:pk>/', views.ShoppingTabDetailView.as_view(), name='shopping-tab-detail'),
    path('shopping-tabs/<int:pk>/delete/', views.ShoppingTabDeleteView.as_view(), name='shopping-tab-delete'),
    path('shopping-tabs/<int:tab_pk>/products/create/', views.ShoppingTabProductCreateView.as_view(), name='shopping-tab-product-create'),
    path('shopping-tabs/<int:tab_pk>/products/<int:product_pk>/edit/', views.ShoppingTabProductUpdateView.as_view(), name='shopping-tab-product-update'),
    path('shopping-tabs/<int:tab_pk>/products/<int:pk>/delete/', views.ShoppingTabProductDeleteView.as_view(), name='shopping-tab-product-delete'),
    path('shopping-tabs/select/<int:product_id>/', views.ShoppingTabSelectionView.as_view(), name='shopping-tab-select'),
    path('shopping-tabs/<int:tab_pk>/add/<int:product_id>/', views.ShoppingTabAddProductView.as_view(), name='shopping-tab-add-product'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
