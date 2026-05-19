from __future__ import annotations

from rest_framework import serializers

from ..models import Brand, Category, CharacteristicType, ImportJob, Product


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
    class Meta:
        model = CharacteristicType
        fields = [
            'id', 'name', 'label', 'value_type', 'options', 'unit', 'required', 'categories',
        ]


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


class ImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportJob
        fields = [
            'id', 'kind', 'status', 'result', 'error',
            'created_at', 'started_at', 'finished_at',
        ]
        read_only_fields = fields
