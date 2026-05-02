from django.urls import path

from .views import SelectFile, DataframeCreateView, DataframeUpdateView

app_name = 'dataframe'

urlpatterns = [
    path('create/', DataframeCreateView.as_view(), name='create'),
    path('<int:pk>/update/', DataframeUpdateView.as_view(), name='update'),
    path('files/select/', SelectFile.as_view(), name='filesselect'),
]
