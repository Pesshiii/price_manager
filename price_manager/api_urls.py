from django.urls import include, path

urlpatterns = [
    path('auth/', include('api_auth.urls', namespace='api_auth')),
    path('dataframe/', include('dataframe.api.urls', namespace='dataframe_api')),
    path('products/', include('product.api.urls', namespace='product_api')),
    path('supplier-feed/', include('supplier_feed.api.urls', namespace='supplier_feed_api')),
    path('suppliers/', include('supplier.api.urls', namespace='supplier_api')),
    path('pricing/', include('pricing.api.urls', namespace='pricing_api')),
]
