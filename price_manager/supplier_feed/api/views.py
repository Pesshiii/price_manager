from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from supplier_feed.models import (
    FeedColumnMapping,
    FeedMapping,
    SupplierFeed,
    SupplierFeedEntry,
    SupplierLink,
    STATUS_DRAFT,
    STATUS_PROCESSING,
)
from supplier_feed.completion import complete_feed
from supplier_feed.tasks import run_feed_matching_task
from dataframe import sessions as session_store
from .serializers import (
    FeedColumnMappingSerializer,
    FeedMappingSerializer,
    SupplierFeedSerializer,
    SupplierFeedDetailSerializer,
    SupplierFeedEntrySerializer,
    SupplierLinkSerializer,
    SupplierLinkPatchSerializer,
)


class _QueuePagination(PageNumberPagination):
    """Paginator for the MatchQueue list. Supports ?page=N&page_size=N."""

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200


class FeedMappingViewSet(viewsets.ModelViewSet):
    """CRUD для конфигурации выгрузок поставщика."""

    serializer_class = FeedMappingSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = FeedMapping.objects.select_related('supplier', 'dataframe').order_by('supplier', 'name')
        supplier = self.request.query_params.get('supplier')
        if supplier:
            qs = qs.filter(supplier_id=supplier)
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Prevent deletion when SupplierFeed sessions reference this mapping.
        feeds = getattr(instance, 'supplier_feeds', None)
        if feeds is not None and feeds.exists():
            return Response(
                {'detail': 'Невозможно удалить конфигурацию: существуют связанные сессии выгрузок.'},
                status=status.HTTP_409_CONFLICT,
            )
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SupplierFeedViewSet(viewsets.ModelViewSet):
    """Lifecycle management for SupplierFeed sessions."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = SupplierFeed.objects.select_related('supplier', 'feed_mapping').order_by('-created_at')
        supplier = self.request.query_params.get('supplier')
        status_filter = self.request.query_params.get('status')
        if supplier:
            qs = qs.filter(supplier_id=supplier)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return SupplierFeedDetailSerializer
        return SupplierFeedSerializer

    # ── File upload ────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='upload', url_name='upload')
    def upload(self, request, pk=None):
        """Accept a multipart file upload; store it as a dataframe session."""
        feed = self.get_object()
        file_obj = request.FILES.get('file')
        if file_obj is None:
            return Response({'detail': 'Файл не передан.'}, status=status.HTTP_400_BAD_REQUEST)

        session_id = session_store.create_session(file_obj, file_obj.name)
        feed.session_ids = list(feed.session_ids) + [session_id]
        feed.save(update_fields=['session_ids'])

        meta = session_store.session_metadata(session_id)
        return Response(meta, status=status.HTTP_201_CREATED)

    # ── File delete ────────────────────────────────────────────────────────

    @action(
        detail=True,
        methods=['delete'],
        url_path=r'files/(?P<session_id>[0-9a-f]{32})',
        url_name='delete-file',
    )
    def delete_file(self, request, pk=None, session_id=None):
        """Remove an uploaded file from a draft feed."""
        feed = self.get_object()
        if feed.status != 'draft':
            return Response(
                {'detail': 'Удаление файлов возможно только для черновиков.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if session_id not in feed.session_ids:
            return Response(
                {'detail': 'Сессия не найдена в данной выгрузке.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        session_store.delete_session(session_id)
        feed.session_ids = [s for s in feed.session_ids if s != session_id]
        feed.save(update_fields=['session_ids'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Trigger matching ───────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='process', url_name='process')
    def process(self, request, pk=None):
        """Validate draft status, set to 'processing', queue the matching task.

        Returns 202 with the current feed state on success.
        Returns 400 if the feed is not in 'draft' status.
        """
        feed = self.get_object()
        if feed.status != STATUS_DRAFT:
            return Response(
                {'detail': 'Обработка возможна только для черновиков.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        feed.status = STATUS_PROCESSING
        feed.save(update_fields=['status'])
        run_feed_matching_task.delay(feed.pk)
        serializer = self.get_serializer(feed)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    # ── MatchQueue list ────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='queue', url_name='queue')
    def queue(self, request, pk=None):
        """Return a paginated list of unmatched, non-skipped entries for this feed.

        An entry appears here when product=None and skipped=False.
        Supports ?page=N&page_size=N.
        """
        feed = self.get_object()
        qs = (
            SupplierFeedEntry.objects
            .filter(feed=feed, product__isnull=True, skipped=False)
            .order_by(models.F('best_score').desc(nulls_first=True))
        )
        paginator = _QueuePagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = SupplierFeedEntrySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    # ── MatchQueue resolve ─────────────────────────────────────────────────────

    @action(
        detail=True,
        methods=['post'],
        url_path=r'queue/(?P<entry_id>\d+)/resolve',
        url_name='resolve',
    )
    def resolve(self, request, pk=None, entry_id=None):
        """Resolve a queued entry by confirming a product or marking as skipped.

        Request body (exactly one of):
          {product_id: <int>}  — confirm match; creates/updates SupplierLink
          {skipped: true}      — mark as "not found"; hides from queue

        Returns 200 with the updated entry on success.
        Returns 400 if the entry is already matched or skipped.
        Returns 404 if the entry does not belong to this feed.
        """
        feed = self.get_object()
        try:
            entry = SupplierFeedEntry.objects.get(pk=entry_id, feed=feed)
        except SupplierFeedEntry.DoesNotExist:
            return Response(
                {'detail': 'Запись не найдена в данной сессии.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Guard against double-resolve.
        if entry.product_id is not None or entry.skipped:
            return Response(
                {'detail': 'Запись уже обработана.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product_id = request.data.get('product_id')
        skipped = request.data.get('skipped')

        if product_id is not None:
            from product.models import Product
            try:
                product = Product.objects.get(pk=product_id)
            except Product.DoesNotExist:
                return Response(
                    {'detail': f'Товар с id={product_id} не найден.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            entry.product = product
            entry.save(update_fields=['product'])

            # Create or update the permanent supplier→product link.
            SupplierLink.objects.update_or_create(
                supplier=feed.supplier,
                supplier_sku=entry.supplier_sku,
                defaults={'product': product},
            )
        elif skipped:
            entry.skipped = True
            entry.save(update_fields=['skipped'])
        else:
            return Response(
                {'detail': 'Необходимо передать product_id или skipped=true.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        complete_feed(feed)

        return Response(SupplierFeedEntrySerializer(entry).data, status=status.HTTP_200_OK)


    # ── Create product from queue entry ───────────────────────────────────────

    @action(
        detail=True,
        methods=['post'],
        url_path=r'queue/(?P<entry_id>\d+)/create-product',
        url_name='create-product',
    )
    def create_product(self, request, pk=None, entry_id=None):
        """Create a new Product from a queued entry and link it.

        Request body: {sku: str, name: str}
        Atomically creates the Product (status=draft), a SupplierLink, and
        resolves the entry.  Returns 201 with the updated entry.
        """
        from django.db import transaction
        from product.models import Product

        feed = self.get_object()
        try:
            entry = SupplierFeedEntry.objects.get(pk=entry_id, feed=feed)
        except SupplierFeedEntry.DoesNotExist:
            return Response(
                {'detail': 'Запись не найдена в данной сессии.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if entry.product_id is not None or entry.skipped:
            return Response(
                {'detail': 'Запись уже обработана.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sku = request.data.get('sku', '').strip()
        name = request.data.get('name', '').strip()
        if not sku or not name:
            return Response(
                {'detail': 'Необходимо передать sku и name.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Product.objects.filter(sku=sku).exists():
            return Response(
                {'detail': f'Товар с артикулом «{sku}» уже существует.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            product = Product.objects.create(sku=sku, name=name)
            SupplierLink.objects.update_or_create(
                supplier=feed.supplier,
                supplier_sku=entry.supplier_sku,
                defaults={'product': product},
            )
            entry.product = product
            entry.save(update_fields=['product'])

        complete_feed(feed)

        return Response(SupplierFeedEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    # ── Bulk-create products from queue ───────────────────────────────────────

    @action(
        detail=True,
        methods=['post'],
        url_path='queue/bulk-create-products',
        url_name='bulk-create-products',
    )
    def bulk_create_products(self, request, pk=None):
        """Create new Products for all remaining queued entries in one request.

        Request body: {name_column: str}
        For each product=None, skipped=False entry:
          - name = entry.data[name_column] (error if missing or empty)
          - sku  = entry.data[feed_mapping.product_sku_column] if set,
                   else entry.supplier_sku
        Behaviour: skip-and-continue on per-entry errors.
        Returns {created, failed, errors: [{entry_id, reason}]}.
        Auto-transitions feed to 'done' if queue empties.
        """
        from django.db import transaction
        from product.models import Product

        feed = self.get_object()
        name_column = request.data.get('name_column', '').strip()
        if not name_column:
            return Response(
                {'detail': 'Необходимо передать name_column.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mapping = feed.feed_mapping
        sku_column = mapping.product_sku_column or ''

        entries = list(
            SupplierFeedEntry.objects
            .filter(feed=feed, product__isnull=True, skipped=False)
        )

        failed_count = 0
        errors = []

        # Phase 1: validate per-entry and collect (entry, name, sku) candidates
        candidates = []
        skus_to_check = set()
        for entry in entries:
            name = str(entry.data.get(name_column) or '').strip()
            if not name:
                failed_count += 1
                errors.append({'entry_id': entry.pk, 'reason': f'Колонка «{name_column}» пуста или отсутствует.'})
                continue

            if sku_column and sku_column in entry.data:
                sku = str(entry.data[sku_column]).strip() or entry.supplier_sku
            else:
                sku = entry.supplier_sku

            candidates.append((entry, name, sku))
            skus_to_check.add(sku)

        # Phase 2: one query to find all conflicting SKUs
        existing_skus = set(
            Product.objects.filter(sku__in=skus_to_check).values_list('sku', flat=True)
        )

        # Phase 3: separate duplicates from entries to create; deduplicate within batch
        to_create = []
        seen_skus = set(existing_skus)
        for entry, name, sku in candidates:
            if sku in seen_skus:
                failed_count += 1
                errors.append({'entry_id': entry.pk, 'reason': f'Товар с артикулом «{sku}» уже существует.'})
            else:
                to_create.append((entry, name, sku))
                seen_skus.add(sku)

        # Phase 4: bulk-insert Products, SupplierLinks, and FeedEntry.product in one transaction
        if to_create:
            try:
                with transaction.atomic():
                    new_products = Product.objects.bulk_create([
                        Product(sku=sku, name=name) for _, name, sku in to_create
                    ])
                    sku_to_product = {p.sku: p for p in new_products}

                    SupplierLink.objects.bulk_create(
                        [
                            SupplierLink(
                                supplier=feed.supplier,
                                supplier_sku=entry.supplier_sku,
                                product=sku_to_product[sku],
                            )
                            for entry, _, sku in to_create
                        ],
                        update_conflicts=True,
                        update_fields=['product'],
                        unique_fields=['supplier', 'supplier_sku'],
                    )

                    for entry, _, sku in to_create:
                        entry.product = sku_to_product[sku]
                    SupplierFeedEntry.objects.bulk_update(
                        [entry for entry, _, _ in to_create],
                        ['product'],
                    )
            except Exception as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        complete_feed(feed)

        return Response(
            {'created': len(to_create), 'failed': failed_count, 'errors': errors},
            status=status.HTTP_200_OK,
        )

    # ── Ignore a queue entry ───────────────────────────────────────────────────

    @action(
        detail=True,
        methods=['post'],
        url_path=r'queue/(?P<entry_id>\d+)/ignore',
        url_name='ignore',
    )
    def ignore(self, request, pk=None, entry_id=None):
        """Mark a queued entry as permanently ignored.

        Creates an ignore-link (SupplierLink with product=None) and sets
        entry.skipped=True.  Returns 200 with the updated entry.
        """
        from django.db import transaction

        feed = self.get_object()
        try:
            entry = SupplierFeedEntry.objects.get(pk=entry_id, feed=feed)
        except SupplierFeedEntry.DoesNotExist:
            return Response(
                {'detail': 'Запись не найдена в данной сессии.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if entry.product_id is not None or entry.skipped:
            return Response(
                {'detail': 'Запись уже обработана.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            SupplierLink.objects.update_or_create(
                supplier=feed.supplier,
                supplier_sku=entry.supplier_sku,
                defaults={'product': None},
            )
            entry.skipped = True
            entry.save(update_fields=['skipped'])

        complete_feed(feed)

        return Response(SupplierFeedEntrySerializer(entry).data, status=status.HTTP_200_OK)


class SupplierLinkViewSet(
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Manage SupplierLink records: list with filters, delete, and reassign product."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'delete', 'patch', 'head', 'options']

    def get_queryset(self):
        qs = SupplierLink.objects.select_related('supplier', 'product').order_by('id')
        supplier = self.request.query_params.get('supplier')
        supplier_sku = self.request.query_params.get('supplier_sku')
        product = self.request.query_params.get('product')
        if supplier:
            qs = qs.filter(supplier_id=supplier)
        if supplier_sku:
            qs = qs.filter(supplier_sku__icontains=supplier_sku)
        if product:
            qs = qs.filter(product_id=product)
        return qs

    def get_serializer_class(self):
        return SupplierLinkSerializer

    def partial_update(self, request, *args, **kwargs):
        """PATCH {product_id} — reassign this link to a different product."""
        instance = self.get_object()
        serializer = SupplierLinkPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.update(instance, serializer.validated_data)
        # Refresh to pick up the new product FK before serialising
        instance.refresh_from_db(fields=['product_id'])
        return Response(SupplierLinkSerializer(instance).data, status=status.HTTP_200_OK)


class FeedColumnMappingViewSet(viewsets.ModelViewSet):
    """CRUD for FeedColumnMapping records nested under a FeedMapping."""

    serializer_class = FeedColumnMappingSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        mapping_pk = self.kwargs['mapping_pk']
        # Raise 404 if parent mapping does not exist
        get_object_or_404(FeedMapping, pk=mapping_pk)
        return FeedColumnMapping.objects.filter(feed_mapping_id=mapping_pk)

    def perform_create(self, serializer):
        mapping_pk = self.kwargs['mapping_pk']
        serializer.save(feed_mapping_id=mapping_pk)
