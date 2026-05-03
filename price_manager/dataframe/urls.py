from django.urls import path

from .views import (
    FileList, FileItem, FileCreate)

app_name = 'dataframe'

urlpatterns = [
    # path('create/', DataframeCreateView.as_view(), name='create'),
    # path('<int:pk>/update/', DataframeUpdateView.as_view(), name='update'),
    # path('table/', DataframeTableView.as_view(), name='table'),
    path('files/create/', FileCreate.as_view(), name='filecreate'),
    path('files/select/<int: pk>', FileItem.as_view(), name='fileitem'),
    path('files/select/', FileList.as_view(), name='filelist'),
]
