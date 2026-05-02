from django.urls import path

from .views import SelectFile

app_name = 'dataframe'

urlpatterns = [
    path('files/select/', SelectFile.as_view(), name='filesselect'),
]
