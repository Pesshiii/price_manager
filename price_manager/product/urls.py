from django.urls import path

from .views import CreateContentType, SelectContentType

app_name = 'product'

urlpatterns = [
    path('contenttype/create/', CreateContentType.as_view(), name='contenttype-create'),
    path('content-type/select/', SelectContentType.as_view(), name='content-type-select'),

]
