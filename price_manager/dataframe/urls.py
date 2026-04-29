
from django.urls import include, path

from .views import Create, Update

app_name = 'dataframe'

urlpatterns = [
    path('create/', Create.as_view(), name='dataframe-create'),
    path('<slug:slug>/update', Update.as_view(), name='dataframe-update'),
]
