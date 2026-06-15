from __future__ import annotations

from rest_framework import serializers

from ..models import (
    Brand,
    Category,
    CharacteristicMutationJob,
    CharacteristicType,
    ImportJob,
    Product,
)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'parent', 'level']
        read_only_fields = ['slug', 'level']


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ['id', 'name', 'slug']
        read_only_fields = ['slug']


class CharacteristicTypeSerializer(serializers.ModelSerializer):
    """CRUD serializer for ``CharacteristicType``.

    ``categories_detail`` is read-only metadata for the SPA detail modal so it
    doesn't have to fan out to ``/categories/?id__in=…`` just to render names.
    The writeable ``categories`` field stays a flat list of PKs.

    ``name`` and ``value_type`` are intentionally rejected by ``update()`` —
    both require a JSONB migration of every product carrying this characteristic,
    which only the dedicated retype/rename endpoints can do safely. See
    ``services/char_mutation.py`` and ``tasks.run_char_retype/run_char_rename``.
    """

    categories_detail = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CharacteristicType
        fields = [
            'id', 'name', 'label', 'value_type', 'options', 'unit', 'required',
            'categories', 'categories_detail',
        ]

    def get_categories_detail(self, obj):
        return [
            {'id': c.id, 'name': c.name, 'level': c.level}
            for c in obj.categories.all()
        ]

    def update(self, instance, validated_data):
        # Block mutations that need a JSONB migration — route them through
        # the dedicated async endpoints instead.
        blocked = {}
        if 'name' in validated_data and validated_data['name'] != instance.name:
            blocked['name'] = (
                'Изменение `name` миграционное: используйте '
                'POST /characteristic-types/<id>/rename/commit/.'
            )
        if (
            'value_type' in validated_data
            and validated_data['value_type'] != instance.value_type
        ):
            blocked['value_type'] = (
                'Изменение `value_type` миграционное: используйте '
                'POST /characteristic-types/<id>/retype/commit/.'
            )
        if blocked:
            raise serializers.ValidationError(blocked)
        return super().update(instance, validated_data)


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            'id', 'sku', 'name', 'category', 'brand', 'description', 'status',
            'characteristics', 'image_urls', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate(self, attrs):
        # Run model.clean() so characteristic JSON gets validated/coerced.
        instance = Product(**{k: v for k, v in attrs.items() if k != 'id'})
        if self.instance is not None:
            instance.pk = self.instance.pk
        try:
            instance.clean()
        except Exception as exc:  # ValidationError or other
            raise serializers.ValidationError(getattr(exc, 'message_dict', None) or {'detail': str(exc)})
        attrs['characteristics'] = instance.characteristics
        return attrs


class _MappingFieldSerializer(serializers.Serializer):
    column = serializers.CharField(required=False, allow_blank=True)
    const = serializers.JSONField(required=False)
    lookup = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if 'column' not in attrs and 'const' not in attrs:
            raise serializers.ValidationError("Поле требует 'column' или 'const'.")
        return attrs


class ImportRequestSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    instructions = serializers.DictField()
    mapping = serializers.DictField()
    row_limit = serializers.IntegerField(required=False, min_value=1, max_value=10000, default=200)
    default_status = serializers.ChoiceField(
        choices=Product.STATUS_CHOICES,
        required=False,
        allow_blank=True,
        default='',
    )


class ImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportJob
        fields = [
            'id', 'kind', 'status', 'stage', 'rows_total', 'rows_done',
            'result', 'error',
            'created_at', 'started_at', 'finished_at',
        ]
        read_only_fields = fields


class CharMutationJobSerializer(serializers.ModelSerializer):
    """Envelope for ``GET /characteristic-types/jobs/<uuid>/`` polling.

    Includes ``stage`` so the SPA can show the worker's current step
    ("Сканируем товары" / "Применяем изменения" / "Обновляем тип").
    """

    char_type = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = CharacteristicMutationJob
        fields = [
            'id', 'kind', 'status', 'stage', 'rows_total', 'rows_done',
            'char_type', 'payload',
            'result', 'error', 'created_at', 'started_at', 'finished_at',
        ]
        read_only_fields = fields
