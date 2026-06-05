from rest_framework import serializers

from ..models import ProductSnapshot, SnapshotField, TransformRule


class SnapshotFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = SnapshotField
        fields = ['id', 'slug', 'name', 'value_type', 'description']


class TransformRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransformRule
        fields = ['id', 'feed_mapping', 'target_field', 'priority', 'condition', 'formula']


class ProductSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSnapshot
        fields = ['id', 'product', 'supplier', 'source_feed', 'data', 'updated_at']
