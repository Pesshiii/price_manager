
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from core import views
from file_manager import views as fm_views
from supplier_product_manager import views as spm_views
from main_product_manager import views as mp_views
from supplier_manager import views as sm_views
from product_price_manager import views as ppm_views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', views.AppLoginView.as_view(), name='login'),
    path('accounts/logout/', views.AppLogoutView.as_view(), name='logout'),

    path('', mp_views.MainPage.as_view(), name='mainproducts'),
    path('mainproduct/table_bycat/<int:category_pk>', mp_views.MainProductTableView.as_view(), name='mainproduct-table-bycat'),
    path('mainproduct/table_nocat/', mp_views.MainProductTableView.as_view(), name='mainproduct-table-nocat'),
    path('mainproduct/resolve/table_bycat/<int:category_pk>', mp_views.MainProductResolveTableView.as_view(), name='mainproductresolve-table-bycat'),
    path('mainproduct/resolve/table_nocat/', mp_views.MainProductResolveTableView.as_view(), name='mainproductresolve-table-nocat'),

    path('mainproduct/<int:id>/update', mp_views.MainProductUpdate.as_view(), name='main-product-update'),
    path('mainproduct/sync', mp_views.sync_main_products, name='mainproducts-sync'),
    path('mainproduct/<int:pk>/info', mp_views.MainProductInfo.as_view(), name='mainproduct-info'),
    path('mainproduct/<int:pk>/update', mp_views.MainProductUpdate.as_view(), name='mainproduct-update'),
    path('mainproduct/<int:pk>/resolve', mp_views.ResolveMainproduct.as_view(), name='mainproduct-resolve'),
    path('mainproduct/<int:pk>/detail', mp_views.MainProductDetail.as_view(), name='mainproduct-detail'),
    path('mainproduct/<int:pk>/pricetags', ppm_views.PriceTagList.as_view(), name='pricetag-list'),
    path('mainproduct/<int:pk>/logs', mp_views.MainProductLogList.as_view(), name='mainproductlog-list'),

    # SUPPLIER WORKFRAME
    
    path('supplier/', sm_views.SupplierList.as_view(), name='supplier'),
    
    path('supplier/<int:pk>/update', sm_views.SupplierUpdate.as_view(), name='supplier-update'),
    path('supplier/<int:id>/delete/', sm_views.SupplierDelete.as_view(), name='supplier-delete'),

    path('supplier/create/', sm_views.SupplierCreate.as_view(), name='supplier-create'),
    path('supplier/<int:pk>/', spm_views.SupplierDetail.as_view(), name='supplier-detail'),

    path('supplier/<int:pk>/upload', spm_views.UploadSupplierFile.as_view(), name='supplier-upload'),
    path('supplier/<int:pk>/copytomain/<int:state>', spm_views.copy_to_main, name='supplier-copymain'),

    path('supplier/<int:pk>/settings/', spm_views.SettingList.as_view(), name='settings'),
    path('setting/<int:pk>/', spm_views.SettingUpdate.as_view(), name='setting-update'),
    path('setting/<int:pk>/table', spm_views.XMLTableView.as_view(), name='setting-table'),
    path('setting/<int:pk>/upload/<int:state>', spm_views.setting_upload, name='setting-upload'),

    path('supplier/<int:pk>/pricemanagers/', ppm_views.PriceManagerList.as_view(), name='pricemanagers'),
    path('pricemanager/<int:pk>/', ppm_views.PriceManagerUpdate.as_view(), name='pricemanager-update'),

    # path('setting/<int:id>/delete', spm_views.SettingDelete.as_view(), name='setting-delete'),
    # path('setting/<int:id>/upload/<int:f_id>/', spm_views.SettingUpdate.as_view(), name='setting-update'),

    ##################################################################################################

    path('category/autocomplete',sm_views.CategoryAutocomplete.as_view(),name='category-autocomplete'),
    
    path('currency/', sm_views.CurrencyList.as_view(), name='currency'),
    path('currency/create/', sm_views.CurrencyCreate.as_view(), name='currency-create'),
    path('currency/<int:id>/update', sm_views.CurrencyUpdate.as_view(), name='currency-update'),

    path('price-manager/', ppm_views.PriceManagerList.as_view(), name='price-manager'),
    path('price-manager/create-for/<int:pk>', ppm_views.PriceManagerCreate.as_view(), name='pricemanager-create'),
    path('price-manager/<int:id>/delete', ppm_views.PriceManagerDelete.as_view(), name='price-manager-delete'),
    
    path('pricetag/create-for/<int:pk>', ppm_views.PriceTagCreate.as_view(), name='pricetag-create'),
    path('pricetag/<int:pk>/update', ppm_views.PriceTagUpdate.as_view(), name='pricetag-update'),

    path('supplier-product/<int:id>/delete/', spm_views.delete_supplier_product, name='supplier-product-delete'),


    path('upload/<str:name>/<int:id>/', fm_views.FileUpload.as_view(), name='upload'),

    path('shopping-tabs/', views.ShoppingTabListView.as_view(), name='shopping-tab-list'),
    path('shopping-tabs/<int:pk>/', views.ShoppingTabDetailView.as_view(), name='shopping-tab-detail'),
    path('shopping-tabs/<int:pk>/delete/', views.ShoppingTabDeleteView.as_view(), name='shopping-tab-delete'),
    path('shopping-tabs/<int:tab_pk>/products/create/', views.ShoppingTabProductCreateView.as_view(), name='shopping-tab-product-create'),
    path('shopping-tabs/<int:tab_pk>/products/<int:product_pk>/edit/', views.ShoppingTabProductUpdateView.as_view(), name='shopping-tab-product-update'),
    path('shopping-tabs/<int:tab_pk>/products/<int:pk>/delete/', views.ShoppingTabProductDeleteView.as_view(), name='shopping-tab-product-delete'),
    path('shopping-tabs/select/<int:product_id>/', views.ShoppingTabSelectionView.as_view(), name='shopping-tab-select'),
    path('shopping-tabs/<int:tab_pk>/add/<int:product_id>/', views.ShoppingTabAddProductView.as_view(), name='shopping-tab-add-product'),


    path('blog/', include('blogapp.urls')),

    path("toasts/", views.toast_messages, name="toast-messages"),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

