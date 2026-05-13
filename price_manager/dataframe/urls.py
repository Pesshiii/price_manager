from django.urls import path

from .views import (
    ContentTypeAutocomplete,
    ContentTypeCreate,
    DataframeCreate,
    DataframeUpdate,
    DataframeFilePreview,
    DataframeResultPreview,
)

app_name = 'dataframe'

urlpatterns = [
    path('create/', DataframeCreate.as_view(), name='create'),
    path('<int:pk>/update', DataframeUpdate.as_view(), name='update'),
    path('contenttype/autocomplete/', ContentTypeAutocomplete.as_view(), name='contenttype-autocomplete'),
    path('contenttype/create/', ContentTypeCreate.as_view(), name='contenttype-create'),
    path('<int:pk>/preview/file/', DataframeFilePreview.as_view(), name='preview-file'),
    path('<int:pk>/preview/result/', DataframeResultPreview.as_view(), name='preview-result'),
]