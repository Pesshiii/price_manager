from django.urls import path

from .views import CreateContentType

app_name = 'product'

urlpatterns = [
    path('contenttype/create/', CreateContentType.as_view(), name='contenttype-create'),

]
