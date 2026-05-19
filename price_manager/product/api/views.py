from __future__ import annotations

from collections import Counter

from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from dataframe import sessions as session_store

from ..filters import ProductFilter
from ..models import Brand, Category, CharacteristicType, ImportJob, Product
from ..tasks import run_import_commit, run_import_preview
from .pagination import (
    CharacteristicTypePagination,
    ProductPagination,
    ReferenceTablePagination,
)
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    CharacteristicTypeSerializer,
    ImportJobSerializer,
    ImportRequestSerializer,
    ProductSerializer,
)


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    pagination_class = ReferenceTablePagination

    def get_queryset(self):
        qs = Category.objects.all()
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class BrandViewSet(viewsets.ModelViewSet):
    serializer_class = BrandSerializer
    pagination_class = ReferenceTablePagination

    def get_queryset(self):
        qs = Brand.objects.all()
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class CharacteristicTypeViewSet(viewsets.ModelViewSet):
    serializer_class = CharacteristicTypeSerializer
    pagination_class = CharacteristicTypePagination

    def get_queryset(self):
        qs = CharacteristicType.objects.all().prefetch_related('categories')
        category_id = self.request.query_params.get('category')
        if category_id:
            qs = qs.filter(categories=category_id)
        search = self.request.query_params.get('search')
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=search) | Q(label__icontains=search))
        # `?name__in=a,b,c` — bulk-fetch metadata for an explicit name list,
        # used by the SPA to label already-bound chars on the import mapping step.
        name_in = self.request.query_params.get('name__in')
        if name_in:
            names = [n.strip() for n in name_in.split(',') if n.strip()]
            if names:
                qs = qs.filter(name__in=names)
        return qs


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    pagination_class = ProductPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProductFilter

    @action(detail=False, methods=['get'])
    def facets(self, request):
        """Aggregate available characteristic values + counts for the current filter set.

        Response shape (self-describing — clients no longer need to fetch the
        full /characteristic-types/ list just to render labels):
            {
              "<char_name>": {
                "label": "<CharacteristicType.label or name>",
                "unit": "<CharacteristicType.unit>",
                "value_type": "string|integer|float|boolean|choice",
                "buckets": [{"value": ..., "count": N}, ...]
              },
              ...
            }
        """
        # Bounds so the response stays small even when the catalog has thousands
        # of distinct char keys (which can happen after EAV-style imports).
        try:
            max_keys = max(1, min(int(request.query_params.get('facets_max_keys', 50)), 500))
        except (TypeError, ValueError):
            max_keys = 50
        try:
            max_buckets = max(1, min(int(request.query_params.get('facets_max_buckets', 30)), 200))
        except (TypeError, ValueError):
            max_buckets = 30

        qs = self.filter_queryset(self.get_queryset())
        counts: dict[str, Counter] = {}
        for chars in qs.values_list('characteristics', flat=True):
            if not isinstance(chars, dict):
                continue
            for key, value in chars.items():
                if isinstance(value, (list, dict)):
                    continue
                counts.setdefault(key, Counter())[value] += 1

        if not counts:
            return Response({})

        # Keep only the most popular keys (by total occurrences across products).
        top_keys = sorted(counts.items(), key=lambda kv: -sum(kv[1].values()))[:max_keys]
        top_dict = dict(top_keys)

        types_by_name = {
            ct.name: ct
            for ct in CharacteristicType.objects.filter(name__in=list(top_dict.keys()))
            .only('name', 'label', 'unit', 'value_type')
        }
        payload = {}
        for key, counter in top_dict.items():
            ct = types_by_name.get(key)
            payload[key] = {
                'label': ct.label if ct else key,
                'unit': ct.unit if ct else '',
                'value_type': ct.value_type if ct else 'string',
                'buckets': [
                    {'value': v, 'count': c}
                    for v, c in counter.most_common(max_buckets)
                ],
            }
        return Response(payload)


def _session_exists(session_id: str) -> bool:
    try:
        session_store.session_metadata(session_id)
    except FileNotFoundError:
        return False
    return True


def _create_import_job(request, kind: str):
    serializer = ImportRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    if not _session_exists(data['session_id']):
        return Response(
            {'detail': f"session {data['session_id']} не найдена или истекла."},
            status=status.HTTP_404_NOT_FOUND,
        )

    job = ImportJob.objects.create(
        user=request.user if request.user.is_authenticated else None,
        kind=kind,
        session_id=data['session_id'],
        instructions=data['instructions'],
        mapping=data['mapping'],
        row_limit=data.get('row_limit') or 200,
    )
    runner = run_import_preview if kind == ImportJob.KIND_PREVIEW else run_import_commit
    runner.delay(str(job.id))
    job.refresh_from_db()
    return Response(ImportJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class ImportPreviewView(APIView):
    def post(self, request):
        return _create_import_job(request, ImportJob.KIND_PREVIEW)


class ImportCommitView(APIView):
    def post(self, request):
        return _create_import_job(request, ImportJob.KIND_COMMIT)


class ImportJobView(APIView):
    def get(self, request, job_id):
        qs = ImportJob.objects.all()
        if request.user.is_authenticated:
            qs = qs.filter(user=request.user)
        else:
            qs = qs.filter(user__isnull=True)
        job = get_object_or_404(qs, pk=job_id)
        return Response(ImportJobSerializer(job).data)
