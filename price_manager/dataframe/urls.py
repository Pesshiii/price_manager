from django.urls import path

from .views import (
    DataframeCreate, DataframeUpdate,
    FileList, FileCreate, FileSelect,
    LinkCreate, LinkUpdate,
    ContentTypeCreate, ContentTypeList, ContentTypeSelect,
    )

app_name = 'dataframe'


# patterns for dataframe

urlpatterns = [
    path('create/', DataframeCreate.as_view(), name='create'),
    path('<int:pk>/update/', DataframeUpdate.as_view(), name='update'),
]

# patterns for files

urlpatterns += [
    path('files/create/', FileCreate.as_view(), name='filecreate'),
    path('files/<int:pk>/select/', FileSelect.as_view(), name='fileselect'),
    path('files/list/', FileList.as_view(), name='filelist'),
]

# patterns for links

urlpatterns += [
    path('<int:df_pk>/link/create/', LinkCreate.as_view(), name='create'),
    path('<int:df_pk>/link/<int:pk>/update/', LinkUpdate.as_view(), name='update'),
]

# patterns for contenttypes

urlpatterns += [
    path('contenttype/create/', ContentTypeCreate.as_view(), name='filecreate'),
    path('contenttype/<int:pk>/select/', ContentTypeSelect.as_view(), name='fileselect'),
    path('contenttype/list/', ContentTypeList.as_view(), name='filelist'),
]