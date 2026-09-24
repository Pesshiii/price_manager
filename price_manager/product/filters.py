from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Field, HTML, Hidden, Layout, Submit
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import connection
from django.db.models import Count, Exists, F, OuterRef, Q
from django_filters import FilterSet, filters

from core.crispy_fields import OobField
from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from .models import Brand, Category, Product


# --- общие части поиска и фасетов --------------------------------------------
#
# Живут на уровне модуля, потому что у них два потребителя: товарная страница
# (ProductFilter, корень — Product) и выбор строк поставщиков
# (main_product_manager.MainProductFilter — корзина, корень — MainProduct).
# Определение поиска должно быть одно на оба места, иначе они разъедутся.

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


def expanded_category_pks(selected) -> set[int]:
    """Ветки дерева, раскрытые при отрисовке: выбранные узлы и их предки.

    Считается здесь одним запросом, а не в шаблоне: там это было пересечение
    потомков узла с выбором — по запросу на каждую ветку, дважды, даже без
    выбора. Пока дерево рисовалось раз на страницу, это терпелось; теперь оно
    перерисовывается после каждого фильтра. selected — список pk.
    """
    if not selected:
        return set()
    return set(
        Category.objects.filter(pk__in=selected)
        .get_ancestors(include_self=True).values_list('pk', flat=True)
    )


def category_subtree_counts(products) -> dict[int, int]:
    """Сколько РАЗНЫХ товаров из products лежит в каждой категории или под ней.

    Считается по поддереву, потому что так же работает сам фильтр
    (category_with_descendants): число рядом с «Сантехникой» обязано совпасть
    с тем, что покажет выбор «Сантехники». Сумма прямых счётчиков потомков
    тут не годится — товар в двух подкатегориях одной ветки был бы посчитан
    дважды.

    Сырой SQL, потому что соединение «узел — его предки» идёт не по внешнему
    ключу, а по интервалам MPTT (tree_id + lft/rght), и ORM его не выражает.
    В выдачу попадают только узлы с товарами; их предки — тоже, так что
    набор замкнут вверх и годится для {% recursetree %} как есть.
    """
    pairs = Product.categories.through.objects.filter(
        product_id__in=products.values('pk')
    ).values('product_id', 'category_id')
    pairs_sql, params = pairs.query.sql_with_params()
    category = connection.ops.quote_name(Category._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT a.id, COUNT(DISTINCT p.product_id) '
            f'FROM ({pairs_sql}) p '
            f'JOIN {category} c ON c.id = p.category_id '
            f'JOIN {category} a ON a.tree_id = c.tree_id '
            f'AND a.lft <= c.lft AND a.rght >= c.rght '
            f'GROUP BY a.id',
            params,
        )
        return dict(cursor.fetchall())


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

    def config_filters(self):
        """Справочники целиком — ТОЛЬКО для проверки выбранных значений.

        Что показать в панели, решает narrow_facets(), и он дорогой: три
        агрегата по всей выдаче. Таблице, экспорту и корзине нужен лишь .qs,
        поэтому здесь ничего не считается — поле всего лишь должно принять
        любой существующий pk из адреса.
        """
        self.filters['brand'].field.queryset = Brand.objects.order_by('name')
        self.filters['supplier'].field.queryset = Supplier.objects.order_by('name')

    # Фасеты, которые сужаются под выдачу. Порядок не важен.
    FACETS = ('categories', 'brand', 'supplier')

    def _queryset_without(self, facet):
        """Товары под всеми условиями, кроме условий самого фасета.

        «Все, кроме своего» — иначе после галочки на Bosch из списка брендов
        пропали бы все остальные, и добавить Makita (бренды внутри фасета
        складываются через ИЛИ) стало бы нельзя.

        Корень — голый Product.objects, а не self.queryset: у выдачи страницы
        аннотации цен и сортировка по категориям, и в агрегате они только
        мешают. Оборачивание в pk__in снимает order_by(rank), который оставляет
        поиск: поле из ORDER BY попало бы в GROUP BY, и каждая группа
        выродилась бы в один товар.
        """
        base = Product.objects.all()
        queryset = base
        for name, value in self.form.cleaned_data.items():
            if name != facet and name in self.filters:
                queryset = self.filters[name].filter(queryset, value)
        if queryset is base:
            return base
        return Product.objects.filter(pk__in=queryset.order_by().values('pk'))

    def narrow_facets(self):
        """Оставляет в фасетах только варианты с товарами и считает их.

        Вызывают только панель фильтров и её обновление (views), не .qs.

        Пишем в self.form.fields, а не в self.filters[...].field: форма при
        создании копирует поля, и запись в поле фильтра до отрисовки уже не
        доходит.

        Выбранное остаётся в списке всегда, даже с нулём: иначе условие,
        сузившее выдачу до пустоты, выкинуло бы собственную галочку, и снять
        её стало бы нечем. Выбранное берётся из cleaned_data — это уже
        проверенные объекты, мусор из адреса сюда не доходит.
        """
        self.form.is_valid()
        data = self.form.cleaned_data
        fields = self.form.fields

        brand_counts = dict(
            self._queryset_without('brand').filter(brand__isnull=False)
            .order_by().values_list('brand').annotate(n=Count('pk'))
        )
        fields['brand'].queryset = Brand.objects.filter(
            Q(pk__in=list(brand_counts)) | Q(pk__in=[b.pk for b in data.get('brand') or []])
        ).order_by('name')
        fields['brand'].facet_counts = brand_counts

        # Товар засчитывается поставщику, если у поставщика есть его строка, —
        # ровно условие supplier_method (отдельный Exists), поэтому число
        # совпадает с тем, что покажет выбор этого поставщика.
        supplier_counts = dict(
            MainProduct.objects.filter(
                product__in=self._queryset_without('supplier').values('pk'),
                supplier__isnull=False,
            ).order_by().values_list('supplier').annotate(n=Count('product', distinct=True))
        )
        fields['supplier'].queryset = Supplier.objects.filter(
            Q(pk__in=list(supplier_counts))
            | Q(pk__in=[s.pk for s in data.get('supplier') or []])
        ).order_by('name')
        fields['supplier'].facet_counts = supplier_counts

        # Узлы с товарами замкнуты вверх сами (см. category_subtree_counts).
        # Выбранному узлу без товаров предков надо добавить явно:
        # {% recursetree %} на узле без родителя в выборке падает с 500.
        # Предки выбранных — это и есть раскрытые ветки, так что один набор
        # служит обеим целям.
        category_counts = category_subtree_counts(self._queryset_without('categories'))
        expanded = expanded_category_pks([c.pk for c in data.get('categories') or []])
        fields['categories'].queryset = (
            Category.objects.filter(pk__in=set(category_counts) | expanded)
            .select_related(CATEGORY_LABEL_DEPTH)
        )
        fields['categories'].facet_counts = category_counts
        fields['categories'].expanded_pks = expanded

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
            Div(Field('available', template='core/includes/switch_field.html'),
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

    def build_facets_helper(self):
        """Хелпер для обновления фасетов: только списки, все — OOB.

        Панель после каждого фильтра не перерисовывается целиком: в ней поля
        цены, быстрый поиск по брендам, раскрытые ветки — всё это слетело бы
        посреди ввода. Заменяются лишь сами списки: у дерева корень
        div_<auto_id>, у галочек — блок #checkboxes из checkbox_field.html
        (строка быстрого поиска лежит вне него и переживает замену). Id те же,
        что у первой отрисовки build_helper, — по ним и идёт замена.
        """
        helper = FormHelper(self.form)
        helper.form_tag = False
        helper.layout = Layout(
            OobField('categories', template='product/partials/category_tree_field.html'),
            OobField('brand', template='core/includes/checkbox_field.html#checkboxes'),
            OobField('supplier', template='core/includes/checkbox_field.html#checkboxes'),
        )
        self.form.helper = helper
        return helper
