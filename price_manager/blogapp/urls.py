from django.urls import path

from .views import ArticleCreateView, ArticleDetailView, ArticleListView, ArticleUpdateView

app_name = 'blogapp'

urlpatterns = [
    path('', ArticleListView.as_view(), name='article-list'),
    path('create/', ArticleCreateView.as_view(), name='article-create'),
    path('<int:pk>/', ArticleDetailView.as_view(), name='article-detail'),
    path('<int:pk>/edit/', ArticleUpdateView.as_view(), name='article-update'),
]
