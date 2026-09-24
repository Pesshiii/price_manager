from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Field, HTML, Hidden, Layout, Submit
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Exists, F, OuterRef, Q
from django_filters import FilterSet, filters

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from .models import Brand, Category, Product, ProductSetItem


# --- общие части поиска и фасетов --------------------------------------------
#
# Живут на уровне модуля, потому что у них два потребителя: товарная страница
# (ProductFilter, корень — Product) и выбор строк поставщиков
# (main_product_manager.MainProductFilter — корзина и «Привязать из ГП»,
# корень — MainProduct). Определение поиска должно быть одно на оба места,
# иначе они разъедутся.

def search_terms(value) -> list[str]:
    return [term for term in (value or '').split() if term]


def selected_values(data, name) -> list:
    """Выбранные значения фасета, независимо от типа data.

    Из представления сюда приходит QueryDict с .getlist(), но фильтр законно
    собирают и на обычном dict — из тестов, из кода. Голый .getlist() на dict
    падает с AttributeError, причём в __init__, то есть роняет любое такое
    использование целиком.
    """
    if not data:
        return []
    if hasattr(data, 'getlist'):
        return data.getlist(name) or []
    value = data.get(name) or []
    return value if isinstance(value, (list, tuple)) else [value]


def search_rank(value, vector='search_vector'):
    """Выражение релевантности для непустого поиска, иначе None.

    F(vector), а НЕ строка. Со строкой Django считает её текстовым полем,
    которое надо векторизовать, и генерирует
    ts_rank(to_tsvector(search_vector::text), …): готовый tsvector приводится к
    тексту и токенизируется заново — на каждой строке, дефолтной конфигурацией
    вместо russian. Индекс при этом не при делах. На 155 тыс. товаров это
    разница между сотнями миллисекунд и секундами.

    vector — путь до поля: 'search_vector' от Product,
    'product__search_vector' от MainProduct.
    """
    if not search_terms(value):
        return None
    return SearchRank(F(vector), SearchQuery(value, config='russian'))


def matching_product_pks(value):
    """pk товаров под запрос: вектор ИЛИ номер ИЛИ название у поставщика.

    Артикул поставщика (MainProduct.article) здесь намеренно не ищется:
    артикул, который пользователь видит в интерфейсе, это sku, а sku и есть
    Product.number — тот самый ключ сопоставления.

    А вот название связанного MainProduct ищется, и это не лишнее: у
    несинхронизированной заготовки вектор состоит из одного number, и без
    этого условия такой товар нельзя найти вообще никак, пока бэкфилл до него
    не дошёл.

    UNION трёх отборов, а не OR трёх условий. По отдельности они дешёвые:
    вектор 36 мс (GIN), number 41 мс, название у поставщика 98 мс. Под общим
    OR Postgres не умеет совместить GIN-скан с подзапросом и проваливается в
    полный проход — 622 мс на один только отбор и ~1.4 с на страницу даже при
    единственном совпадении. UNION даёт каждой ветке её собственный план, а
    потом один semi-join по pk.
    """
    terms = search_terms(value)

    by_number = Q()
    for term in terms:
        by_number &= Q(number__icontains=term)

    by_main_product_name = Q()
    for term in terms:
        by_main_product_name &= Q(name__icontains=term)

    return (
        Product.objects.filter(search_vector=SearchQuery(value, config='russian'))
        .values('pk')
        .union(
            Product.objects.filter(by_number).values('pk'),
            MainProduct.objects.filter(by_main_product_name, product__isnull=False)
            .values('product_id'),
        )
    )


def ranked(queryset, value, vector='search_vector'):
    """Сортировка выдачи поиска по релевантности.

    nulls_last обязателен. '-rank' компилируется в ORDER BY rank DESC, а
    Postgres при DESC ставит NULL ПЕРВЫМИ. Вектора нет у ~100 тыс. товаров без
    данных PIM, и их rank — NULL, поэтому ВСЯ первая страница заполнялась
    самыми слабыми совпадениями (по номеру или по названию у поставщика), а
    настоящие полнотекстовые — на «молоток» их 463 — на неё не попадали вовсе.
    pk вторым ключом — чтобы пагинация была стабильной при равном rank.
    """
    return (
        queryset
        .annotate(rank=search_rank(value, vector))
        .order_by(F('rank').desc(nulls_last=True), 'pk')
    )


def category_with_descendants(categories) -> set[int]:
    """Выбор родителя должен находить всё, что под ним.

    Разворачиваем выбор по дереву ЛОКАЛЬНО, через MPTT. Без этого выбор
    «Сантехника» вернул бы только товары, привязанные ровно к этому узлу, а не
    к «Сантехника > Смесители» — то есть заметно меньше, чем ожидается, и
    молча.
    """
    pks = set()
    for category in categories:
        pks.update(category.get_descendants(include_self=True).values_list('pk', flat=True))
    return pks


# Глубина 5 покрывает всё дерево (уровни 0-5). Category.__str__ рекурсивно идёт
# по self.parent, и без предзагрузки каждая метка стоит по запросу на уровень.
# На боевом дереве это 1567 запросов и 1.6 с против одного запроса и 36 мс —
# метки при этом получаются те же самые.
CATEGORY_LABEL_DEPTH = 'parent__parent__parent__parent__parent'


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
        fields = ['search', 'categories', 'brand', 'supplier', 'available', 'is_set', 'contains']

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
        # select_related обязателен — см. CATEGORY_LABEL_DEPTH.
        queryset=Category.objects.select_related(CATEGORY_LABEL_DEPTH),
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

    is_set = filters.BooleanFilter(
        method='is_set_method',
        label='Только наборы',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    # «Наборы, в которые входит товар» — ссылка «в N наборах» под названием
    # компонента (ProductTable.render_display_name). В панели фильтров поля нет,
    # только скрытое: иначе смена любого другого фильтра его бы сбросила.
    contains = filters.NumberFilter(
        method='contains_method',
        widget=forms.HiddenInput(),
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
        return selected_values(self.data, name)

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

    def search_method(self, queryset, name, value):
        if not search_terms(value):
            return queryset
        return ranked(queryset.filter(pk__in=matching_product_pks(value)), value)

    # --- контентные фасеты (зеркало PIM) ----------------------------------

    def categories_method(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Exists(Product.categories.through.objects.filter(
                product_id=OuterRef('pk'),
                category_id__in=category_with_descendants(value),
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

    # --- наборы (ProductSetItem) -------------------------------------------

    def is_set_method(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Exists(ProductSetItem.objects.filter(set_product=OuterRef('pk'))))

    def contains_method(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(Exists(ProductSetItem.objects.filter(
            set_product=OuterRef('pk'), component_id=value)))

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
        # Задержки хватает, чтобы успеть отметить несколько галочек одним
        # заходом; больше — и страница кажется зависшей. Пока запрос идёт,
        # #products-results приглушён (см. product/list.html).
        helper.attrs = {
            'hx-get': url,
            'hx-swap': 'outerHTML',
            'hx-trigger': 'input changed delay:600ms, change delay:600ms, submit',
            'hx-push-url': 'true',
            'hx-include': '#products-search',
            'hx-indicator': '#products-results',
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
            Field('contains'),
            Div(Field('available', template='core/includes/switch_field.html'),
                Field('is_set', template='core/includes/switch_field.html'),
                css_class='filter-section'),
            Div(HTML('<div class="filter-section-title">Себестоимость</div>'),
                Div(Field('price_from'), Field('price_to'), css_class='d-flex gap-2 price-range'),
                css_class='filter-section'),
            Div(Field('categories', template='product/partials/category_tree_field.html'),
                css_class='filter-section'),
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
