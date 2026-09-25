from django import forms

from product.models import Brand, Category

from .models import ProductPriceRule, ProductPriceType


class ProductPriceTypeForm(forms.ModelForm):
    class Meta:
        model = ProductPriceType
        fields = ['name', 'pim_field', 'show_on_page', 'sorting']


class ProductPriceRuleForm(forms.ModelForm):
    """Форма наценки. Отрисовывается вручную (partials/rule_form.html), а не crispy:
    категории и бренды — поиск с «чипами» выбранного вместо списков на сотни
    строк, редкие поля свёрнуты в «Дополнительно».
    """

    name = forms.CharField(label='Название', required=False, max_length=255,
                           help_text='Пусто — соберётся из настроек.')

    class Meta:
        model = ProductPriceRule
        fields = [
            'price_type', 'source',
            'markup', 'increase', 'fixed_price', 'rounding',
            'categories', 'brands', 'only_sets', 'price_from', 'price_to',
            'name', 'date_from', 'date_to', 'priority', 'is_active',
        ]
        widgets = {
            'date_from': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'date_to': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    # Поля, которые живут в «Дополнительно»: секция раскрыта, если в них есть
    # ошибка или непустое значение — иначе сделанный выбор спрятался бы.
    ADVANCED = ('name', 'date_from', 'date_to', 'priority', 'is_active')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['price_type'].empty_label = None
        self.fields['categories'].queryset = Category.objects.all()
        self.fields['brands'].queryset = Brand.objects.all()

    def selected_pks(self, name) -> set[str]:
        value = self[name].value() or []
        return {str(getattr(item, 'pk', item)) for item in value}

    def category_options(self) -> list[dict]:
        """Дерево категорий плоским списком в порядке обхода, с путём для поиска.

        Путь собирается в памяти по parent_id: Category.__str__ ходил бы в базу
        за каждым предком.
        """
        selected = self.selected_pks('categories')
        nodes = list(Category.objects.order_by('tree_id', 'lft').values('pk', 'name', 'parent_id', 'level'))
        by_pk = {node['pk']: node for node in nodes}
        options = []
        for node in nodes:
            path, parent = [], by_pk.get(node['parent_id'])
            while parent is not None:
                path.append(parent['name'])
                parent = by_pk.get(parent['parent_id'])
            options.append({
                'pk': node['pk'], 'name': node['name'], 'level': node['level'],
                'path': ' › '.join(reversed(path)), 'selected': str(node['pk']) in selected,
            })
        return options

    def brand_options(self) -> list[dict]:
        selected = self.selected_pks('brands')
        return [
            {'pk': pk, 'name': name, 'level': 0, 'path': '', 'selected': str(pk) in selected}
            for pk, name in Brand.objects.order_by('name').values_list('pk', 'name')
        ]

    def advanced_open(self) -> bool:
        if any(self[name].errors for name in self.ADVANCED):
            return True
        instance = self.instance
        return bool(instance.pk and (instance.date_from or instance.date_to
                                     or instance.priority != 100 or not instance.is_active))

    def clean(self):
        """Пустое название собирается здесь, а не в save(): модель требует
        name, и проверка модели (_post_clean) идёт раньше save()."""
        cleaned = super().clean()
        if not cleaned.get('name') and cleaned.get('price_type'):
            draft = ProductPriceRule(**{
                field: cleaned.get(field) for field in (
                    'price_type', 'source', 'markup', 'increase', 'fixed_price', 'rounding', 'only_sets')
            })
            cleaned['name'] = auto_name(draft, cleaned.get('categories'), cleaned.get('brands'))
        return cleaned


def auto_name(rule, categories=None, brands=None) -> str:
    """«Розничная: Себестоимость + 35 % · Смесители» — чтобы в списке было видно суть."""
    name = f'{rule.price_type.name}: {rule.formula_label()}'
    scope = [c.name for c in (categories or [])][:2] + [b.name for b in (brands or [])][:2]
    if rule.only_sets:
        scope.append('наборы')
    if scope:
        name += ' · ' + ', '.join(scope)
    return name[:255]
