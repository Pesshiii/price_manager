from django.urls import path

from .views import SelectFile, DataframeCreateView, DataframeUpdateView, FileMetaView, DataframeTableView

app_name = 'dataframe'

urlpatterns = [
    path('create/', DataframeCreateView.as_view(), name='create'),
    path('<int:pk>/update/', DataframeUpdateView.as_view(), name='update'),
    path('files/select/', SelectFile.as_view(), name='filesselect'),
    path('files/<int:pk>/meta/', FileMetaView.as_view(), name='filesmeta'),
    path('table/', DataframeTableView.as_view(), name='table'),
]
