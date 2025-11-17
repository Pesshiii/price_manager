from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from file_manager.views import FileUpload
from main_price import views as main_views
from price_manager_app import views as price_views
from setting_manager import views as setting_views
from shoping_cart import views as cart_views
from supplier_manager import views as supplier_views
from tutorials.views import InstructionsView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', main_views.AppLoginView.as_view(), name='login'),
    path('accounts/logout/', main_views.AppLogoutView.as_view(), name='logout'),
    path('', main_views.MainPage.as_view(), name='main'),
    path('main/filter-options/', main_views.MainFilterOptionsView.as_view(), name='main-filter-options'),
    path('main/table/', main_views.MainTableView.as_view(), name='main-table'),
    path('instructions/', InstructionsView.as_view(), name='instructions'),
    path('supplier/', supplier_views.SupplierList.as_view(), name='supplier'),
    path('supplier/<int:id>/', supplier_views.SupplierDetail.as_view(), name='supplier-detail'),
    path('supplier/<int:id>/update', supplier_views.SupplierUpdate.as_view(), name='supplier-update'),
    path('supplier/<int:id>/delete/', supplier_views.SupplierDelete.as_view(), name='supplier-delete'),
    path('supplier/<int:id>/settings/', setting_views.SupplierSettingList.as_view(), name='supplier-settings'),
    path('supplier/create/', supplier_views.SupplierCreate.as_view(), name='supplier-create'),
    path('supplier/<int:id>/setting/create/<int:f_id>/', setting_views.SettingCreate.as_view(), name='setting-create'),
    path('setting/<int:id>/', setting_views.SettingDetail.as_view(), name='setting-detail'),
    path('setting/<int:id>/delete', setting_views.SettingDelete.as_view(), name='setting-delete'),
    path('setting/<int:id>/upload/<int:f_id>/', setting_views.SettingUpdate.as_view(), name='setting-update'),
    path('setting/<int:id>/upload/<int:f_id>/upload', setting_views.SettingUpload.as_view(), name='setting-upload'),
    path('category/autocomplete', main_views.CategoryAutocomplete.as_view(), name='category-autocomplete'),
    path('currency/', supplier_views.CurrencyList.as_view(), name='currency'),
    path('currency/create/', supplier_views.CurrencyCreate.as_view(), name='currency-create'),
    path('currency/<int:id>/update', supplier_views.CurrencyUpdate.as_view(), name='currency-update'),
    path('price-manager/', price_views.PriceManagerList.as_view(), name='price-manager'),
    path('price-manager/<int:id>/', price_views.PriceManagerUpdate.as_view(), name='price-manager-update'),
    path('price-manager/create/', price_views.PriceManagerCreate.as_view(), name='price-manager-create'),
    path('price-manager/<int:id>/delete', price_views.PriceManagerDelete.as_view(), name='price-manager-delete'),
    path('supplier-product/<int:id>/delete/', supplier_views.delete_supplier_product, name='supplier-product-delete'),
    path('main-product/<int:id>/update', main_views.MainProductUpdate.as_view(), name='main-product-update'),
    path('main-product/sync/', main_views.sync_main_products, name='main-product-sync'),
    path('upload/<str:name>/<int:id>/', FileUpload.as_view(), name='upload'),
    path('shopping-tabs/', cart_views.ShoppingTabListView.as_view(), name='shopping-tab-list'),
    path('shopping-tabs/<int:pk>/', cart_views.ShoppingTabDetailView.as_view(), name='shopping-tab-detail'),
    path('shopping-tabs/<int:pk>/delete/', cart_views.ShoppingTabDeleteView.as_view(), name='shopping-tab-delete'),
    path('shopping-tabs/<int:tab_pk>/products/create/', cart_views.ShoppingTabProductCreateView.as_view(), name='shopping-tab-product-create'),
    path('shopping-tabs/<int:tab_pk>/products/<int:product_pk>/edit/', cart_views.ShoppingTabProductUpdateView.as_view(), name='shopping-tab-product-update'),
    path('shopping-tabs/<int:tab_pk>/products/<int:pk>/delete/', cart_views.ShoppingTabProductDeleteView.as_view(), name='shopping-tab-product-delete'),
    path('shopping-tabs/select/<int:product_id>/', cart_views.ShoppingTabSelectionView.as_view(), name='shopping-tab-select'),
    path('shopping-tabs/<int:tab_pk>/add/<int:product_id>/', cart_views.ShoppingTabAddProductView.as_view(), name='shopping-tab-add-product'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
