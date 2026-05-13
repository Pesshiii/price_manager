from django.urls import path

from .views import (
    ContentTypeAutocomplete,
    ContentTypeCreate,
    DataframeCreate,
    DataframeUpdate,
)

app_name = 'dataframe'

urlpatterns = [
    path('create/', DataframeCreate.as_view(), name='create'),
    path('<int:pk>/update', DataframeUpdate.as_view(), name='update'),
    path('contenttype/autocomplete/', ContentTypeAutocomplete.as_view(), name='contenttype-autocomplete'),
    path('contenttype/create/', ContentTypeCreate.as_view(), name='contenttype-create'),
]