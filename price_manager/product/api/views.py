from __future__ import annotations

from collections import Counter

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from dataframe import sessions as session_store
from dataframe.models import Dataframe
from dataframe.services import apply as apply_pipeline

from ..filters import ProductFilter
from ..importer import apply_mapping, commit_rows
from ..models import Brand, Category, CharacteristicType, Product
from .pagination import ProductPagination
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    CharacteristicTypeSerializer,
    ImportRequestSerializer,
    ProductSerializer,
)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class BrandViewSet(viewsets.ModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer


class CharacteristicTypeViewSet(viewsets.ModelViewSet):
    serializer_class = CharacteristicTypeSerializer

    def get_queryset(self):
        qs = CharacteristicType.objects.all().prefetch_related('categories')
        category_id = self.request.query_params.get('category')
        if category_id:
            qs = qs.filter(categories=category_id)
        return qs


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    pagination_class = ProductPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProductFilter

    @action(detail=False, methods=['get'])
    def facets(self, request):
        """Aggregate available characteristic values + counts for the current filter set."""
        qs = self.filter_queryset(self.get_queryset())
        counts: dict[str, Counter] = {}
        for chars in qs.values_list('characteristics', flat=True):
            if not isinstance(chars, dict):
                continue
            for key, value in chars.items():
                if isinstance(value, (list, dict)):
                    continue
                counts.setdefault(key, Counter())[value] += 1
        payload = {
            key: [{'value': v, 'count': c} for v, c in counter.most_common()]
            for key, counter in counts.items()
        }
        return Response(payload)


def _open_session_or_404(session_id: str):
    try:
        return session_store.open_session_file(session_id)
    except FileNotFoundError:
        return None


def _run_pipeline(session_id: str, instructions: dict):
    """Returns (dataframe, error_response). Caller must handle either."""
    file_obj = _open_session_or_404(session_id)
    if file_obj is None:
        return None, Response(
            {'detail': f'session {session_id} не найдена или истекла.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    df_obj = Dataframe(name='_import', instructions=dict(instructions))
    try:
        df = apply_pipeline(df_obj, file_obj)
    except Exception as exc:  # noqa: BLE001 — surface pipeline errors to the client
        return None, Response(
            {'error': {'message': f'{type(exc).__name__}: {exc}'}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        try:
            file_obj.close()
        except Exception:
            pass
    return df, None


class ImportPreviewView(APIView):
    def post(self, request):
        serializer = ImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        df, err = _run_pipeline(data['session_id'], data['instructions'])
        if err is not None:
            return err

        results = apply_mapping(df, data['mapping'])
        limit = data['row_limit']
        preview_rows = [r.to_json() for r in results[:limit]]
        valid = sum(1 for r in results if r.is_valid)
        return Response({
            'rows': preview_rows,
            'total': len(results),
            'returned': len(preview_rows),
            'valid': valid,
            'invalid': len(results) - valid,
        })


class ImportCommitView(APIView):
    def post(self, request):
        serializer = ImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        df, err = _run_pipeline(data['session_id'], data['instructions'])
        if err is not None:
            return err

        results = apply_mapping(df, data['mapping'])
        summary = commit_rows(results)
        return Response(summary, status=status.HTTP_200_OK)
