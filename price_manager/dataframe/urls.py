from django.urls import path

from . import views

app_name = 'dataframe'

urlpatterns = [
    path('', views.DataframeListView.as_view(), name='list'),
    path('create/', views.DataframeCreateView.as_view(), name='create'),
    path('<int:pk>/edit/', views.DataframeUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', views.DataframeDeleteView.as_view(), name='delete'),
    path('modal/create/', views.DataframeModalCreateView.as_view(), name='modal-create'),
    path('preview/', views.PreviewView.as_view(), name='preview'),
    path('<int:pk>/convert-to-csv/', views.ConvertToCsvView.as_view(), name='convert-to-csv'),
    path('demo/', views.DemoView.as_view(), name='demo'),
]
