from rest_framework.routers import DefaultRouter

from .views import ArticleViewSet

app_name = 'articles_api'

router = DefaultRouter()
router.register(r'', ArticleViewSet, basename='article')

urlpatterns = router.urls
