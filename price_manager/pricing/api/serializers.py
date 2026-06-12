from rest_framework import serializers

from pricing.models import PriceType, PricingRule, ProductPrice, Stock


class PriceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceType
        fields = ['id', 'name', 'label']


class PricingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingRule
        fields = '__all__'
        read_only_fields = ['id']


class ProductPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductPrice
        fields = ['id', 'product', 'supplier', 'price_type', 'value', 'rule', 'updated_at']
        read_only_fields = ['updated_at']


class StockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stock
        fields = ['id', 'product', 'supplier', 'quantity', 'updated_at']
        read_only_fields = ['updated_at']
