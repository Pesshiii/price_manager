from django_filters import filters, FilterSet
from .models import Category, Product
from django import forms

from django.urls import reverse_lazy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML, Hidden


class ProductFilter(FilterSet):
    class Meta:
        model = Product
        fields = ['search', 'category']

    search = filters.CharFilter(
        method='search_method',
        label='Поиск товаров',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Название или артикул',
                'class': 'form-control',
            }
        )
    )

    category = filters.ModelMultipleChoiceFilter(
        queryset=Category.objects.all(),
        method='category_method',
        label='Категория',
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, url=None, hx_target='#product-cards', **kwargs):
        super().__init__(*args, **kwargs)
        self.form.helper = FormHelper(self.form)
        self.form.helper.form_id = 'product-filter'
        self.form.helper.form_method = 'GET'
        self.form.helper.label_class = 'mt-2'
        self.form.helper.attrs = {
            'hx-get': url or reverse_lazy('product:product-list'),
            'hx-swap': 'innerHTML',
            'hx-trigger': 'input changed delay:2s, change delay:2s, submit',
            'hx-push-url': 'true',
            'hx-target': hx_target,
        }
        self.form.helper.layout = Layout(
            Hidden('bound', 'true'),
            HTML('<h5 class="mb-3">Фильтры товаров</h5>'),
            Div(Field('search'), css_class='mb-3'),
            HTML('<hr class="border-secondary">'),
            Div(Field('category'), css_class='mb-3'),
            HTML('<hr class="border-secondary">'),
            Div(
                Submit('action', 'Применить', css_class='btn btn-primary flex-grow-1'),
                Submit('action', 'Сбросить', css_class='btn btn-secondary flex-grow-1'),
                css_class='d-flex gap-2',
            ),
        )

    def search_method(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(name__icontains=value)

    def category_method(self, queryset, name, value):
        if not value:
            return queryset
        descendants = Category.objects.none()
        for cat in value:
            descendants |= cat.get_descendants(include_self=True)
        return queryset.filter(category__in=descendants)
