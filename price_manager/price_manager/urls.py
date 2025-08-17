
from django.contrib import admin
from django.urls import path
from core import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.MainPage.as_view(), name='main'),
    
    path('supplier/', views.SupplierList.as_view(), name='supplier'),
    path('supplier/<int:id>/', views.SupplierDetail.as_view(), name='supplier-detail'),
    path('supplier/<int:id>/settings/', views.SupplierSettingList.as_view(), name='supplier-settings'),
    path('supplier/create/', views.SupplierCreate.as_view(), name='supplier-create'),
    path('supplier/<int:id>/setting/create/<int:f_id>/', views.SettingCreate.as_view(), name='setting-create'),

    path('setting/<int:id>/', views.SettingDetail.as_view(), name='setting-detail'),
    path('setting/<int:id>/upload/<int:f_id>/', views.SettingUpload.as_view(), name='setting-upload'),
    path('setting/<int:id>/upload/<int:f_id>/upload/', views.upload_supplier_products, name='supplier-product-upload'),

    path('manufacturer/', views.ManufacturerList.as_view(), name='manufacturer'),
    path('manufacturer/<int:id>/', views.ManufacturerDetail.as_view(), name='manufacturer-detail'),
    path('manufacturer/<int:id>/add-alt/', views.ManufacturerDictCreate.as_view(), name='manufacturer-dict-create'),
    path('manufacturer/create/', views.ManufacturerCreate.as_view(), name='manufacturer-create'),
    
    path('category/', views.CategoryList.as_view(), name='category'),
    path('category/<int:id>/delete/', views.CategoryDelete.as_view(), name='category-delete'),
    path('category/sort/', views.CategorySortSupplierProduct.as_view(), name='category-sort'),
    path('category/create/', views.CategoryCreate.as_view(), name='category-create'),


    path('currency/', views.CurrencyList.as_view(), name='currency'),
    path('currency/create/', views.CurrencyCreate.as_view(), name='currency-create'),
    path('currency/<int:id>/update', views.CurrencyUpdate.as_view(), name='currency-update'),

    path('price-manager/', views.PriceManagerList.as_view(), name='price-manager'),
    path('price-manager/create/', views.PriceManagerCreate.as_view(), name='price-manager-create'),
    path('price-manager/<int:id>/', views.PriceManagerDetail.as_view(), name='price-manager-detail'),
    path('price-manger/<int:id>/apply', views.price_manager_apply, name='price-manager-apply'),

    path('supplier-product/<int:id>/delete/', views.delete_supplier_product, name='supplier-product-delete'),

    path('upload/<str:name>/<int:id>/', views.FileUpload.as_view(), name='upload'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
