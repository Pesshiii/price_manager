from django.urls import path

from .views import (
    DataframeCreate, DataframeUpdate,
    FileList, FileCreate, FileSelect)

app_name = 'dataframe'

urlpatterns = [
    path('create/', DataframeCreate.as_view(), name='create'),
    path('<int:pk>/update/', DataframeUpdate.as_view(), name='update'),
    # path('table/', DataframeTableView.as_view(), name='table'),
    path('files/create/', FileCreate.as_view(), name='filecreate'),
    path('files/select/<int:pk>', FileSelect.as_view(), name='fileselect'),
    path('files/list/', FileList.as_view(), name='filelist'),
]
