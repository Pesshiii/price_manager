from django.urls import path

from .views import Create, Update, file_handler

app_name = 'dataframe'

urlpatterns = [
    path('create/', Create.as_view(), name='create'),
    path('<slug:slug>/update', Update.as_view(), name='update'),
    path('filehandler/', file_handler, name='filehandler'),
]
