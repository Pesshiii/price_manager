from rest_framework import serializers

from supplier_feed.models import (
    FeedColumnMapping,
    FeedMapping,
    SupplierFeed,
    SupplierFeedEntry,
    SupplierLink,
)


# ── SupplierLink serializers ──────────────────────────────────────────────────

class _SupplierMinSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class _ProductMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    sku = serializers.CharField()


class SupplierLinkSerializer(serializers.ModelSerializer):
    """Read serializer — nested supplier and product objects."""

    supplier = _SupplierMinSerializer(read_only=True)
    product = _ProductMiniSerializer(read_only=True, allow_null=True)

    class Meta:
        model = SupplierLink
        fields = ['id', 'supplier', 'supplier_sku', 'product']


class SupplierLinkPatchSerializer(serializers.Serializer):
    """Write serializer for PATCH — accepts {product_id} and reassigns the link."""

    product_id = serializers.IntegerField()

    def validate_product_id(self, value):
        from product.models import Product
        if not Product.objects.filter(pk=value).exists():
            raise serializers.ValidationError(
                f'Товар с id={value} не найден.'
            )
        return value

    def update(self, instance, validated_data):
        instance.product_id = validated_data['product_id']
        instance.save(update_fields=['product_id'])
        return instance


# ── SupplierFeedEntry (queue) serializer ─────────────────────────────────────

class SupplierFeedEntrySerializer(serializers.ModelSerializer):
    """Read serializer for the MatchQueue list."""

    class Meta:
        model = SupplierFeedEntry
        fields = ['id', 'supplier_sku', 'data', 'match_candidates', 'best_score']


# ── FeedMapping / SupplierFeed serializers ────────────────────────────────────

class _DataframeMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class FeedMappingSerializer(serializers.ModelSerializer):
    dataframe_detail = _DataframeMiniSerializer(source='dataframe', read_only=True)

    class Meta:
        model = FeedMapping
        fields = [
            'id',
            'supplier',
            'name',
            'dataframe',
            'dataframe_detail',
            'supplier_sku_column',
            'identity_columns',
            'variable_columns',
            'auto_match_threshold',
            'product_name_column',
            'product_sku_column',
        ]


class SupplierFeedSerializer(serializers.ModelSerializer):
    """List / create serializer — no per-entry stats."""

    class Meta:
        model = SupplierFeed
        fields = [
            'id',
            'supplier',
            'feed_mapping',
            'status',
            'session_ids',
            'error',
            'created_at',
        ]
        read_only_fields = ['status', 'session_ids', 'error', 'created_at']


class SupplierFeedDetailSerializer(SupplierFeedSerializer):
    """Detail serializer — adds computed entry statistics."""

    total = serializers.SerializerMethodField()
    matched = serializers.SerializerMethodField()
    queued = serializers.SerializerMethodField()
    skipped = serializers.SerializerMethodField()

    class Meta(SupplierFeedSerializer.Meta):
        fields = SupplierFeedSerializer.Meta.fields + ['total', 'matched', 'queued', 'skipped']

    def get_total(self, obj) -> int:
        return obj.entries.count()

    def get_matched(self, obj) -> int:
        return obj.entries.exclude(product=None).count()

    def get_queued(self, obj) -> int:
        return obj.entries.filter(product=None, skipped=False).count()

    def get_skipped(self, obj) -> int:
        return obj.entries.filter(skipped=True).count()


# ── FeedColumnMapping serializer ──────────────────────────────────────────────

class FeedColumnMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedColumnMapping
        fields = ['id', 'feed_mapping', 'column_name', 'role', 'price_type']
        read_only_fields = ['feed_mapping']

    def validate(self, data):
        # On creation the instance is None; on update we fall back to the
        # stored value for any field omitted from a partial PATCH.
        instance = self.instance
        role = data.get('role', getattr(instance, 'role', None))
        price_type = data.get('price_type', getattr(instance, 'price_type', None))
        if role == FeedColumnMapping.ROLE_PRICE and price_type is None:
            raise serializers.ValidationError(
                {'price_type': 'Тип цены обязателен при роли "price".'}
            )
        return data

    def validate_column_name(self, value):
        # Guard against duplicate (feed_mapping, column_name) within this mapping.
        # feed_mapping_id is injected via perform_create / already on instance.
        request = self.context.get('request')
        view = self.context.get('view')
        if view is None:
            return value
        mapping_pk = view.kwargs.get('mapping_pk')
        if mapping_pk is None:
            return value
        qs = FeedColumnMapping.objects.filter(
            feed_mapping_id=mapping_pk,
            column_name=value,
        )
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                'Колонка с таким именем уже добавлена для этой конфигурации выгрузки.'
            )
        return value
