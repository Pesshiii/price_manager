from django.urls import path

from .views import fileupload as fm_views

app_name = 'dataframe'

urlpatterns = [
    path('files/select/', fm_views.SelectFile.as_view(), name='fileselect'),
]
