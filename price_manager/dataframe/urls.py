from django.urls import path

from .views import (
    DataframeCreate, DataframeUpdate
    )

app_name = 'dataframe'


# patterns for dataframe

urlpatterns = [
    path('create/', DataframeCreate.as_view(), name='create'),
    path('<int:pk>/update', DataframeUpdate.as_view(), name='update')
]