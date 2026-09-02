from rest_framework import serializers

from pricing.models import PriceType, PricingRule


class PriceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceType
        fields = ['id', 'name', 'label']


class PricingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingRule
        fields = '__all__'
        read_only_fields = ['id']
