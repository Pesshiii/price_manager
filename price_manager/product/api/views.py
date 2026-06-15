from __future__ import annotations

from collections import Counter

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from pricing.models import ProductPrice

from dataframe import sessions as session_store

from ..filters import ProductFilter
from ..models import (
    Brand,
    Category,
    CharacteristicMutationJob,
    CharacteristicType,
    ImportJob,
    Product,
)
from ..services.char_mutation import (
    RENAME_CONFLICT_STRATEGIES,
    RETYPE_FALLBACKS,
    preview_rename,
    preview_retype,
)
from ..tasks import (
    run_char_rename,
    run_char_retype,
    run_import_commit,
    run_import_preview,
)
from .pagination import (
    CharacteristicTypePagination,
    ProductPagination,
    ReferenceTablePagination,
)
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    CharacteristicTypeSerializer,
    CharMutationJobSerializer,
    ImportJobSerializer,
    ImportRequestSerializer,
    ProductSerializer,
)


_TRUE = {'1', 'true', 'yes', 'y', 'on'}
_FALSE = {'0', 'false', 'no', 'n', 'off'}


def _parse_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    s = raw.strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return None


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
        params = self.request.query_params

        # `?category=` supports both single value and repeated multi-value form.
        # ``getlist`` returns all repetitions for ``?category=1&category=2`` and
        # a single-element list for ``?category=1`` — uniform handling either way.
        category_ids = [v for v in params.getlist('category') if v]
        if category_ids:
            qs = qs.filter(categories__in=category_ids).distinct()

        search = params.get('search')
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=search) | Q(label__icontains=search))

        value_type = params.get('value_type')
        if value_type:
            qs = qs.filter(value_type=value_type)

        required = _parse_bool(params.get('required'))
        if required is not None:
            qs = qs.filter(required=required)

        # `?name__in=a,b,c` — bulk-fetch metadata for an explicit name list,
        # used by the SPA to label already-bound chars on the import mapping step.
        name_in = params.get('name__in')
        if name_in:
            names = [n.strip() for n in name_in.split(',') if n.strip()]
            if names:
                qs = qs.filter(name__in=names)
        return qs

    # ----- migration-aware actions for name / value_type changes -----------

    @action(detail=True, methods=['post'], url_path='retype/preview')
    def retype_preview(self, request, pk=None):
        ct = self.get_object()
        new_value_type = request.data.get('new_value_type')
        if not new_value_type:
            return Response(
                {'new_value_type': 'Поле обязательно.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_value_type not in dict(CharacteristicType.VALUE_TYPE_CHOICES):
            return Response(
                {'new_value_type': f'Неизвестный тип {new_value_type!r}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(preview_retype(ct, new_value_type))

    @action(detail=True, methods=['post'], url_path='retype/commit')
    def retype_commit(self, request, pk=None):
        ct = self.get_object()
        new_value_type = request.data.get('new_value_type')
        fallback = request.data.get('fallback', 'drop')
        if not new_value_type:
            return Response(
                {'new_value_type': 'Поле обязательно.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_value_type not in dict(CharacteristicType.VALUE_TYPE_CHOICES):
            return Response(
                {'new_value_type': f'Неизвестный тип {new_value_type!r}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if fallback not in RETYPE_FALLBACKS:
            return Response(
                {'fallback': f'Стратегия должна быть одной из {RETYPE_FALLBACKS}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = {
            'new_value_type': new_value_type,
            'fallback': fallback,
            'default_value': request.data.get('default_value'),
            'value_map': request.data.get('value_map') or {},
        }
        job = CharacteristicMutationJob.objects.create(
            user=request.user if request.user.is_authenticated else None,
            char_type=ct,
            kind=CharacteristicMutationJob.KIND_RETYPE,
            payload=payload,
        )
        run_char_retype.delay(str(job.id))
        job.refresh_from_db()
        return Response(
            CharMutationJobSerializer(job).data, status=status.HTTP_202_ACCEPTED
        )

    @action(detail=True, methods=['post'], url_path='rename/preview')
    def rename_preview(self, request, pk=None):
        ct = self.get_object()
        new_name = (request.data.get('new_name') or '').strip()
        if not new_name:
            return Response(
                {'new_name': 'Поле обязательно.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_name == ct.name:
            return Response(
                {'new_name': 'Новое имя должно отличаться от текущего.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if CharacteristicType.objects.filter(name=new_name).exclude(pk=ct.pk).exists():
            return Response(
                {'new_name': f"Тип с именем '{new_name}' уже существует."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(preview_rename(ct, new_name))

    @action(detail=True, methods=['post'], url_path='rename/commit')
    def rename_commit(self, request, pk=None):
        ct = self.get_object()
        new_name = (request.data.get('new_name') or '').strip()
        on_conflict = request.data.get('on_conflict', 'overwrite')
        if not new_name:
            return Response(
                {'new_name': 'Поле обязательно.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_name == ct.name:
            return Response(
                {'new_name': 'Новое имя должно отличаться от текущего.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if CharacteristicType.objects.filter(name=new_name).exclude(pk=ct.pk).exists():
            return Response(
                {'new_name': f"Тип с именем '{new_name}' уже существует."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if on_conflict not in RENAME_CONFLICT_STRATEGIES:
            return Response(
                {'on_conflict': f'Должна быть одной из {RENAME_CONFLICT_STRATEGIES}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = {'new_name': new_name, 'on_conflict': on_conflict}
        job = CharacteristicMutationJob.objects.create(
            user=request.user if request.user.is_authenticated else None,
            char_type=ct,
            kind=CharacteristicMutationJob.KIND_RENAME,
            payload=payload,
        )
        run_char_rename.delay(str(job.id))
        job.refresh_from_db()
        return Response(
            CharMutationJobSerializer(job).data, status=status.HTTP_202_ACCEPTED
        )


class CharMutationJobView(APIView):
    """Polling endpoint for retype/rename jobs (mirrors ``ImportJobView``)."""

    def get(self, request, job_id):
        qs = CharacteristicMutationJob.objects.all()
        if request.user.is_authenticated:
            qs = qs.filter(user=request.user)
        else:
            qs = qs.filter(user__isnull=True)
        job = get_object_or_404(qs, pk=job_id)
        return Response(CharMutationJobSerializer(job).data)


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    pagination_class = ProductPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProductFilter

    def get_queryset(self):
        qs = super().get_queryset()
        # Skip price Prefetch for actions (like facets) that don't use the
        # serializer — the prefetch is wasted there and only costs DB work.
        slugs = self.request.query_params.getlist('price_types')
        if slugs and self.action not in ('facets',):
            qs = qs.prefetch_related(
                Prefetch(
                    'prices',
                    queryset=ProductPrice.objects.filter(
                        price_type__name__in=slugs
                    ).select_related('price_type'),
                    to_attr='_price_annotations',
                )
            )
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['price_types'] = self.request.query_params.getlist('price_types')
        return ctx


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

    # Priority: explicit request param > mapping-level default > ''
    effective_status = (
        data.get('default_status')
        or (data['mapping'] or {}).get('default_status', '')
    )
    job = ImportJob.objects.create(
        user=request.user if request.user.is_authenticated else None,
        kind=kind,
        session_id=data['session_id'],
        instructions=data['instructions'],
        mapping=data['mapping'],
        row_limit=data.get('row_limit') or 200,
        default_status=effective_status,
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
