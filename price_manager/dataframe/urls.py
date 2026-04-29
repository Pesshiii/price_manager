from django.urls import path

from .views import Create, Update, jsonform_file_handler

app_name = 'dataframe'

urlpatterns = [
    path('create/', Create.as_view(), name='create'),
    path('<slug:slug>/update', Update.as_view(), name='update'),
    path('json-file-handler/', jsonform_file_handler, name='json-file-handler'),
]
