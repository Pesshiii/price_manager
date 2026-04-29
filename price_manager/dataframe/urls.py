from django.urls import path

from .views import Create, Update

app_name = 'dataframe'

urlpatterns = [
    path('create/', Create.as_view(), name='create'),
    path('<slug:slug>/update', Update.as_view(), name='update'),
]
