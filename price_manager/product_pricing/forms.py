from django import forms

from product.filters import CATEGORY_LABEL_DEPTH
from product.models import Brand, Category

from .models import ProductPriceRule, ProductPriceType


class ProductPriceTypeForm(forms.ModelForm):
    class Meta:
        model = ProductPriceType
        fields = ['name', 'pim_field', 'show_on_page', 'sorting']


class ProductPriceRuleForm(forms.ModelForm):
    class Meta:
        model = ProductPriceRule
        fields = [
            'name', 'price_type', 'source',
            'markup', 'increase', 'fixed_price', 'rounding',
            'categories', 'brands', 'price_from', 'price_to',
            'date_from', 'date_to', 'priority', 'is_active',
        ]
        widgets = {
            'categories': forms.SelectMultiple(attrs={'size': 10}),
            'brands': forms.SelectMultiple(attrs={'size': 8}),
            'date_from': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'date_to': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Метка категории — Category.__str__, путь до корня: без select_related
        # это запрос на каждый уровень каждого варианта.
        self.fields['categories'].queryset = (
            Category.objects.select_related(CATEGORY_LABEL_DEPTH).order_by('tree_id', 'lft'))
        self.fields['brands'].queryset = Brand.objects.order_by('name')
        self.fields['fixed_price'].help_text = 'Только для «От какой цены считать» = «Фиксированная цена».'
