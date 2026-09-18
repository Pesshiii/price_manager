from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Field, HTML, Hidden, Layout, Submit
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Exists, F, OuterRef, Q
from django_filters import FilterSet, filters

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from .models import Brand, Category, Product


class ProductFilter(FilterSet):
    """Фильтр товарной страницы. Корень выборки — Product, а не MainProduct.

    Три источника условий, и это осознанное разделение:
      1. search_vector на Product — свободный текст, локально;
      2. категории и бренд — контент PIM, зеркалируемый в product.Category и
         product.Brand;
      3. остаток и цены — поля MainProduct, через обратную связь main_products.

    Любой проход по main_products — это join, который размножает строки, поэтому
    здесь везде Exists(), а не filter() по связанной модели. distinct() решил бы
    ту же задачу, но он же убил бы сортировку по рангу: DISTINCT требует, чтобы
    выражение из ORDER BY попало в список выборки, а ранг считается только при
    непустом поиске.
    """

    class Meta:
        model = Product
        fields = ['search', 'categories', 'brand', 'supplier', 'available']

    search = filters.CharFilter(
        method='search_method',
        label='Поиск товаров',
        widget=forms.TextInput(attrs={
            # id задаётся явно: по нему и hx-trigger строки поиска, и
            # hx-include формы фильтров. По умолчанию Django выдал бы
            # id_search, оба селектора молча не нашли бы ничего — поиск не
            # срабатывал бы вовсе, а применение фильтра стирало бы уже
            # введённый запрос.
            'id': 'products-search',
            'placeholder': 'Название, артикул или ключевое слово',
            'class': 'form-control',
        }),
    )

    categories = filters.ModelMultipleChoiceFilter(
        queryset=Category.objects.all(),
        method='categories_method',
        label='Категории',
        widget=forms.CheckboxSelectMultiple(),
    )

    brand = filters.ModelMultipleChoiceFilter(
        queryset=Brand.objects.none(),
        method='brand_method',
        label='Бренды',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check'}),
    )

    supplier = filters.ModelMultipleChoiceFilter(
        queryset=Supplier.objects.none(),
        method='supplier_method',
        label='Поставщики',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check'}),
    )

    available = filters.BooleanFilter(
        method='available_method',
        label='Товары в наличии',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    price_from = filters.NumberFilter(
        method='price_from_method',
        label='Себестоимость от',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
    )

    price_to = filters.NumberFilter(
        method='price_to_method',
        label='Себестоимость до',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '∞'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_filters()

    # --- фасеты -----------------------------------------------------------

    def _selected(self, name):
        """Выбранные значения фасета, независимо от типа self.data.

        Из представления сюда приходит QueryDict с .getlist(), но фильтр
        законно собирают и на обычном dict — из тестов, из кода. Голый
        .getlist() на dict падает с AttributeError, причём в __init__, то есть
        роняет любое такое использование целиком.
        """
        data = self.data
        if not data:
            return []
        if hasattr(data, 'getlist'):
            return data.getlist(name) or []
        value = data.get(name) or []
        return value if isinstance(value, (list, tuple)) else [value]

    def config_filters(self):
        """Наполняет списки фасетов и держит уже выбранное наверху.

        Бренды и поставщики ограничены тем, что реально встречается, иначе
        список брендов — это весь справочник PIM. Выбранное подмешивается
        обратно: иначе снятие последнего товара из выборки выкинуло бы галочку
        из списка, и снять её стало бы нечем.
        """
        selected_brands = self._selected('brand')
        brands = Brand.objects.filter(products__isnull=False).distinct().order_by('name')
        if selected_brands:
            brands = Brand.objects.filter(
                Q(pk__in=brands) | Q(pk__in=selected_brands)
            ).order_by('name')
        self.filters['brand'].field.queryset = brands

        selected_suppliers = self._selected('supplier')
        suppliers = Supplier.objects.filter(main_products__isnull=False).distinct().order_by('name')
        if selected_suppliers:
            suppliers = Supplier.objects.filter(
                Q(pk__in=suppliers) | Q(pk__in=selected_suppliers)
            ).order_by('name')
        self.filters['supplier'].field.queryset = suppliers

    # --- поиск ------------------------------------------------------------

    @staticmethod
    def search_rank(value):
        """Выражение релевантности для непустого поиска, иначе None.

        F('search_vector'), а НЕ строка 'search_vector'. Со строкой Django
        считает её текстовым полем, которое надо векторизовать, и генерирует
        ts_rank(to_tsvector(search_vector::text), …): готовый tsvector
        приводится к тексту и токенизируется заново — на каждой строке, дефолтной
        конфигурацией вместо russian. Индекс при этом не при делах. На 155 тыс.
        товаров это разница между сотнями миллисекунд и секундами.
        MainProductFilter.search_rank написан со строкой и болеет тем же.
        """
        if not [term for term in (value or '').split() if term]:
            return None
        return SearchRank(F('search_vector'), SearchQuery(value, config='russian'))

    def search_method(self, queryset, name, value):
        """Вектор ИЛИ артикул ИЛИ название у поставщика.

        Артикул поставщика (MainProduct.article) намеренно не ищется: артикул,
        который пользователь видит в интерфейсе, это sku, а sku и есть
        Product.number — тот самый ключ сопоставления.

        А вот название связанного MainProduct ищется, и это не лишнее: у
        несинхронизированной заготовки вектор состоит из одного number, и без
        этого условия такой товар нельзя найти вообще никак, пока бэкфилл до
        него не дошёл.
        """
        terms = [term for term in (value or '').split() if term]
        if not terms:
            return queryset

        by_number = Q()
        for term in terms:
            by_number &= Q(number__icontains=term)

        by_main_product_name = Q()
        for term in terms:
            by_main_product_name &= Q(name__icontains=term)
        has_named_main_product = Exists(
            MainProduct.objects.filter(product=OuterRef('pk')).filter(by_main_product_name)
        )

        rank = self.search_rank(value)
        return queryset.annotate(rank=rank).filter(
            Q(search_vector=SearchQuery(value, config='russian'))
            | by_number
            | has_named_main_product
        ).order_by('-rank')

    # --- контентные фасеты (зеркало PIM) ----------------------------------

    def categories_method(self, queryset, name, value):
        """Выбор родителя должен находить всё, что под ним.

        Разворачиваем выбор по дереву ЛОКАЛЬНО, через MPTT. Без этого выбор
        «Сантехника» вернул бы только товары, привязанные ровно к этому узлу, а
        не к «Сантехника > Смесители» — то есть заметно меньше, чем страница
        отдаёт сегодня, и молча.
        """
        if not value:
            return queryset
        descendant_ids = set()
        for category in value:
            descendant_ids.update(
                category.get_descendants(include_self=True).values_list('pk', flat=True)
            )
        return queryset.filter(
            Exists(Product.categories.through.objects.filter(
                product_id=OuterRef('pk'), category_id__in=descendant_ids,
            ))
        )

    def brand_method(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(brand__in=value)

    # --- остатки и цены (поля MainProduct) --------------------------------

    def _with_main_product(self, queryset, condition):
        return queryset.filter(
            Exists(MainProduct.objects.filter(product=OuterRef('pk')).filter(condition))
        )

    def supplier_method(self, queryset, name, value):
        if not value:
            return queryset
        return self._with_main_product(queryset, Q(supplier__in=value))

    def available_method(self, queryset, name, value):
        if not value:
            return queryset
        return self._with_main_product(queryset, Q(stock__gt=0))

    def price_from_method(self, queryset, name, value):
        if value is None:
            return queryset
        return self._with_main_product(queryset, Q(prime_cost__gte=value))

    def price_to_method(self, queryset, name, value):
        if value is None:
            return queryset
        return self._with_main_product(queryset, Q(prime_cost__lte=value))

    # --- отрисовка --------------------------------------------------------

    def build_helper(self, url, hx_target: str | None = '#products-table'):
        """Crispy-хелпер для product/partials/filter.html.

        Держится вне __init__ намеренно: почти всем вызывающим нужен только
        .qs, и платить за сборку формы на каждом инстансе незачем.
        """
        helper = FormHelper(self.form)
        helper.form_id = 'product-filter'
        helper.form_method = 'GET'
        helper.label_class = 'mt-2'
        helper.attrs = {
            'hx-get': url,
            'hx-swap': 'outerHTML',
            'hx-trigger': 'input changed delay:2s, change delay:2s, submit',
            'hx-push-url': 'true',
            'hx-include': '#products-search',
        }
        if hx_target:
            helper.attrs['hx-target'] = hx_target
        helper.layout = Layout(
            Hidden('bound', 'true'),
            HTML('''
              <div class="filter-header d-flex align-items-center gap-2 mb-3">
                <i class="bi bi-sliders text-primary"></i>
                <h5 class="mb-0">Фильтры товаров</h5>
              </div>
            '''),
            Div(Field('available', template='core/includes/switch_field.html'),
                css_class='filter-section'),
            Div(HTML('<div class="filter-section-title">Себестоимость</div>'),
                Div(Field('price_from'), Field('price_to'), css_class='d-flex gap-2'),
                css_class='filter-section'),
            Div(Field('categories'), css_class='filter-section'),
            Div(Field('brand', template='core/includes/checkbox_field.html'),
                css_class='filter-section'),
            Div(Field('supplier', template='core/includes/checkbox_field.html'),
                css_class='filter-section filter-section-last'),
            Div(
                Submit('action', 'Применить', title='Применить',
                       css_class='btn btn-primary flex-grow-1'),
                HTML(f'<a href="{url}" class="btn btn-outline-secondary" title="Сбросить">'
                     '<i class="bi bi-arrow-counterclockwise"></i></a>'),
                css_class='d-flex gap-2 filter-actions',
            ),
        )
        self.form.helper = helper
        return helper
