
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
    path('api/', include('api_urls')),
    path('accounts/login/', views.AppLoginView.as_view(), name='login'),
    path('accounts/logout/', views.AppLogoutView.as_view(), name='logout'),

    path('', views.mainpage, name='mainpage'),

    # SUPPLIER WORKFRAME

    path('mainproduct/', include('main_product_manager.urls')),
    
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
    path('setting/<int:pk>/sps', spm_views.SettingSPSTableView.as_view(), name='setting-sps-table'),
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
    path('shopping-tabs/<int:pk>/items/add/', views.ShoppingTabAddItemView.as_view(), name='shopping-tab-item-add'),
    path('shopping-tabs/<int:pk>/delete/', views.ShoppingTabDeleteView.as_view(), name='shopping-tab-delete'),
    path('cart-items/<int:pk>/', views.CartItemDetailView.as_view(), name='cart-item-detail'),
    path('cart-items/<int:pk>/products/select/', views.CartItemProductSelectView.as_view(), name='cart-item-products-select'),
    path('cart-items/<int:pk>/products/add/', views.CartItemAddProductsView.as_view(), name='cart-item-products-add'),
    path('cart-items/<int:pk>/confirm/<int:product_pk>/', views.CartItemConfirmProductView.as_view(), name='cart-item-confirm'),
    path('cart-items/<int:pk>/unconfirm/', views.CartItemUnconfirmView.as_view(), name='cart-item-unconfirm'),
    path('cart-items/<int:pk>/products/<int:product_pk>/remove/', views.CartItemRemoveProductView.as_view(), name='cart-item-product-remove'),
    path('blog/', include('blogapp.urls')),
    path('api/', include('api_urls')),

    path("toasts/", views.toast_messages, name="toast-messages"),
    path('notifications/<int:pk>/delete/', views.PersistentNotificationDeleteView.as_view(), name='persistent-notification-delete'),
    path('notifications/panel/', views.PersistentNotificationsPanelView.as_view(), name='persistent-notifications-panel'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
