from django.urls import path

from .views import ConfSourceView, Create, Update

app_name = 'dataframe'

urlpatterns = [
    path('create/', Create.as_view(), name='dataframe-create'),
    path('<slug:slug>/update', Update.as_view(), name='dataframe-update'),
    path('conf-source/', ConfSourceView.as_view(), name='dataframe-conf-source'),
]
