from rest_framework import permissions, viewsets

from articles.models import Article
from .serializers import ArticleDetailSerializer, ArticleListSerializer


class IsAuthorOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.author_id == request.user.id


class ArticleViewSet(viewsets.ModelViewSet):
    queryset = Article.objects.select_related('author').all()
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.action == 'list':
            return ArticleListSerializer
        return ArticleDetailSerializer

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
