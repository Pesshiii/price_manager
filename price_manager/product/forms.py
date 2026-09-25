from django import forms

from .models import Brand, Category, Product


def category_picker_options(selected) -> list[dict]:
    """Дерево категорий плоским списком в порядке обхода, с путём для поиска —
    для product_pricing/partials/picker.html.

    Путь собирается в памяти по parent_id: Category.__str__ ходил бы в базу
    за каждым предком. selected — множество pk строками.
    """
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


def brand_picker_options(selected) -> list[dict]:
    return [
        {'pk': pk, 'name': name, 'level': 0, 'path': '', 'selected': str(pk) in selected}
        for pk, name in Brand.objects.order_by('name').values_list('pk', 'name')
    ]


def selected_pks(bound_field) -> set[str]:
    value = bound_field.value()
    if value in (None, ''):
        return set()
    if not isinstance(value, (list, tuple)):
        value = [value]
    return {str(getattr(item, 'pk', item)) for item in value}


class ProductForm(forms.ModelForm):
    """Правка товара с карточки.

    Название, бренд и категории у товара с данными из PIM (raw_data непуст)
    приходят оттуда и перезаписываются каждой синхронизацией
    (services/pim_sync.apply_pim_product) — у такого товара они только
    показываются, править их надо в PIM. У товара без данных PIM (большинство)
    правится всё. Артикул локальный всегда: PIM его не присылает.
    """

    PIM_FIELDS = ('name', 'brand', 'categories')

    class Meta:
        model = Product
        fields = ['number', 'name', 'brand', 'categories']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['number'].required = False
        self.fields['number'].help_text = (
            'Ключ привязки строк ГП: новые строки с таким артикулом (sku) привяжутся к этому товару.')
        self.fields['categories'].queryset = Category.objects.all()
        self.fields['brand'].queryset = Brand.objects.all()
        if self.from_pim:
            for name in self.PIM_FIELDS:
                self.fields[name].disabled = True

    @property
    def from_pim(self) -> bool:
        return bool(self.instance.raw_data)

    def category_options(self):
        return category_picker_options(selected_pks(self['categories']))

    def brand_options(self):
        return brand_picker_options(selected_pks(self['brand']))

    def clean_number(self):
        """Пустой артикул — NULL, а не '': уникальность по Lower(number)
        считает две пустые строки одинаковыми, а два NULL — нет."""
        number = (self.cleaned_data.get('number') or '').strip() or None
        if number:
            other = Product.objects.filter(number__iexact=number).exclude(pk=self.instance.pk).first()
            if other:
                raise forms.ValidationError(f'Этот артикул уже у товара «{other.display_name}».')
        return number

    def save(self, commit=True):
        product = super().save(commit=commit)
        if commit:
            # Вектор поиска собирается из данных PIM с откатом на локальные
            # название, бренд и категории — после save_m2m, чтобы категории
            # уже были записаны.
            product.rebuild_search_vector()
        return product
