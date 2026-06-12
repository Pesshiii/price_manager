from rest_framework import serializers

from supplier_feed.models import (
    FeedColumnMapping,
    FeedMapping,
    FeedMarkupRule,
    FeedMarkupSet,
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


# ── FeedMarkupSet / FeedMarkupRule serializers ───────────────────────────────

class FeedMarkupRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedMarkupRule
        fields = ['id', 'markup_set', 'order', 'price_from', 'price_to', 'markup', 'increase']

    def validate(self, data):
        price_from = data.get('price_from', getattr(self.instance, 'price_from', None))
        price_to = data.get('price_to', getattr(self.instance, 'price_to', None))
        if price_from is not None and price_to is not None and price_from > price_to:
            raise serializers.ValidationError(
                {'price_to': 'Цена «до» должна быть не меньше цены «от».'}
            )
        return data


class FeedMarkupSetSerializer(serializers.ModelSerializer):
    rules = FeedMarkupRuleSerializer(many=True, read_only=True)

    class Meta:
        model = FeedMarkupSet
        fields = ['id', 'feed_mapping', 'name', 'price_column', 'output_column', 'rules']


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


class FeedColumnMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedColumnMapping
        fields = ['id', 'feed_mapping', 'column_name', 'role', 'price_type']

    def validate(self, attrs):
        # For PATCH requests only the submitted fields are in attrs; fall back to
        # the instance values so that a partial update cannot silently clear
        # price_type on an existing price-role record.
        role = attrs.get('role', getattr(self.instance, 'role', None))
        price_type = attrs.get('price_type', getattr(self.instance, 'price_type_id', None))
        if role == FeedColumnMapping.ROLE_PRICE and not price_type:
            raise serializers.ValidationError({'price_type': 'Обязательно для роли "Цена".'})
        return attrs


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
