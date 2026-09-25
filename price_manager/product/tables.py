import django_tables2 as tables
from django.contrib.postgres.fields import ArrayField
from django.db.models import (
    Count, F, Func, IntegerField, Max, Min, OuterRef, Q, Subquery, Sum, Window,
)
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import number_format
from django.utils.html import format_html, format_html_join

from main_product_manager.models import MainProduct
from product_pricing.models import ProductPriceType

from .columns import COLUMN_LABELS, DEFAULT_COLUMNS, PRODUCT_ROW_COLUMNS, SUPPLIER_ROW_COLUMNS
from .models import Product

# Ровно эта строка, когда остаток не синхронизировался ни разу: NULL в stock —
# третье состояние, а не ноль.
NO_STOCK_DATA = 'Нет данных'

# Заголовок группы товаров, у которых нет ни одной категории из PIM.
UNCATEGORIZED = 'Без категории'


def in_sets_label(count):
    """«в 1 наборе», «в 3 наборах» — после «в» у числительного всегда предложный."""
    return f'в {count} наборе' if count % 10 == 1 and count % 100 != 11 else f'в {count} наборах'


def set_cost_html(totals):
    """Себестоимость набора из комплектующих — с пометкой, если она неполная.

    Сумма показывается и у неполного набора: так видно, сколько уже набрано
    и чего не хватает. Но без пометки она выдавала бы себя за полную.
    """
    if totals.cost is None:
        value = format_html('<span class="text-body-tertiary">{}</span>', '—')
    else:
        value = format_html('<span class="text-nowrap">{}</span>', number_format(totals.cost, decimal_pos=2))
    if not totals.missing_cost:
        return value
    return format_html(
        '{} <span class="set-incomplete" title="Сумма без компонентов, у которых нет цены '
        'или которых нет в Price Manager">нет цены у {} из {}</span>',
        value, totals.missing_cost, totals.count)


def _money(value):
    """Цена в ячейке; ноль приглушён — он чаще значит «цены нет», чем «бесплатно»."""
    text = number_format(value, decimal_pos=2)
    if not value:
        return format_html('<span class="text-body-tertiary">{}</span>', text)
    return format_html('{}', text)


def annotate_product_rows(queryset, by_category=False):
    """Агрегаты по связанным MainProduct для строки товара.

    Настоящая агрегация по Product.main_products, а не оконные функции. Старая
    главная считала то же самое окнами (grouping.py, удалён в Phase 2b) только
    потому, что её корнем был плоский MainProduct и группы приходилось
    изображать. Здесь группа это строка, поэтому окна не нужны.

    distinct=True у Count обязателен: при by_category к выборке присоединены
    categories, и без него поставщики посчитались бы с кратностью категорий.

    by_category — выдача по категориям (см. ProductPage.groups_by_category):
    товары упорядочены по положению своей категории в дереве, внутри неё — по
    названию, товары без категорий в конце. Ключ — агрегат по join на
    categories, а не коррелированный подзапрос: подзапрос в ORDER BY
    считается на каждой из 158 тыс. строк, и на снапшоте прода это 8 с на
    страницу против ~0,5 с сейчас; join укладывается в те же ~0,5–0,7 с.

    Join на categories размножает строки MainProduct на число категорий
    товара. Count(distinct) и Min/Max это переживают, Sum — нет: остаток
    товара с двумя категориями удвоился бы. Поэтому в этом режиме total_stock
    считается подзапросом. Он не в ORDER BY, и Postgres вычисляет его уже после
    LIMIT — для 25 строк страницы, а не для всех. Вне этого режима остаток
    остаётся Sum: по нему можно сортировать, и тогда подзапрос считался бы на
    каждой строке (2,6 с против 0,5 с).
    """
    total_stock = Sum('main_products__stock')
    extra = {}
    if by_category:
        total_stock = Subquery(
            MainProduct.objects.filter(product=OuterRef('pk'))
            .order_by().values('product').annotate(total=Sum('stock')).values('total')
        )
        extra['category_key'] = Min(_category_tree_position(), filter=Q(categories__isnull=False))

    queryset = queryset.annotate(
        supplier_count=Count('main_products__supplier', distinct=True),
        total_stock=total_stock,
        min_prime_cost=Min('main_products__prime_cost'),
        max_prime_cost=Max('main_products__prime_cost'),
        in_stock_count=Count('main_products', filter=Q(main_products__stock__gt=0), distinct=True),
        # Резерв для артикула, если у самого Product number=NULL (см.
        # render_number) — на проде это не только «ещё не синхронизировался»:
        # часть таких строк — Product-дубликаты с привязанным MainProduct,
        # чей sku давно занят другим Product.number (главный keeper-файл
        # product.md документирует историю). Min, а не First: агрегация, без
        # доп. запроса на строку.
        number_fallback=Min('main_products__sku'),
        **extra,
    )
    if by_category:
        queryset = queryset.order_by(
            F('category_key').asc(nulls_last=True), F('name').asc(nulls_last=True), 'pk')
    return queryset


def best_match_groups_first(queryset):
    """Порядок поиска в выдаче по категориям.

    Группы — по лучшему совпадению в них, внутри группы — по релевантности.
    Нужны обе аннотации: rank (filters.ranked) и category_key
    (annotate_product_rows(by_category=True)). Второй ключ — category_key:
    при равном лучшем совпадении две группы всё равно не перемешаются.

    nulls_last везде по той же причине, что в filters.ranked: у товаров без
    данных PIM вектора нет и rank — NULL, а DESC ставит NULL первыми. Группа,
    где все совпадения такие (по номеру или названию у поставщика), уходит в
    конец.
    """
    group_rank = Window(Max('rank'), partition_by=[F('category_key')])
    return queryset.order_by(
        group_rank.desc(nulls_last=True),
        F('category_key').asc(nulls_last=True),
        F('rank').desc(nulls_last=True),
        'pk',
    )


def _category_tree_position():
    """ARRAY[tree_id, lft] — место категории в обходе дерева MPTT.

    Массив, а не два отдельных Min(tree_id) и Min(lft): у товара с двумя
    категориями они взялись бы от разных категорий, и ключ не указывал бы ни
    на одну из них — товар встал бы в чужую группу. Массивы Postgres
    сравнивает поэлементно, так что Min(массива) — это ровно первая категория
    в порядке дерева (корни — по tree_id, внутри корня — по lft).
    """
    return Func(F('categories__tree_id'), F('categories__lft'), function='ARRAY',
                template='%(function)s[%(expressions)s]',
                output_field=ArrayField(IntegerField()))


def primary_category(product):
    """Категория, под заголовком которой товар стоит в выдаче по категориям.

    Правило обязано совпадать с category_key из annotate_product_rows — первая
    категория в порядке дерева. Разойдись они, товар встал бы по одной
    категории, а заголовок над ним показал бы другую. Категории берутся из
    предзагрузки (_base_queryset), без запросов.
    """
    return min(product.categories.all(), key=lambda category: (category.tree_id, category.lft),
               default=None)


def category_path(category):
    """Путь от корня до категории: ['Крепеж', 'Нержавеющий крепеж', …].

    Родители уже загружены — предзагрузка категорий в _base_queryset идёт с
    select_related на всю глубину дерева (CATEGORY_LABEL_DEPTH).
    """
    names = []
    while category is not None:
        names.append(category.name)
        category = category.parent
    return names[::-1]


def with_category_headers(rows):
    """Пары (заголовок, строка) для страницы в выдаче по категориям.

    Заголовок — путь категории — стоит над первой строкой каждой группы и над
    первой строкой страницы: группа, начатая на предыдущей странице, без него
    читалась бы как часть той, что выше. У остальных строк заголовок None.
    """
    result = []
    previous = object()
    for row in rows:
        category = primary_category(row.record)
        key = category.pk if category else None
        header = None
        if key != previous:
            header = category_path(category) if category else [UNCATEGORIZED]
        previous = key
        result.append((header, row))
    return result


def product_price_html(price):
    """Расчётная цена в ячейке; в подсказке — из чего и каким правилом она получена."""
    if price is None:
        return format_html('<span class="text-body-tertiary">{}</span>', '—')
    hint = f'Наценка: {price.rule.name}' if price.rule_id and price.rule else 'Наценка удалена'
    if price.source_value is not None:
        hint += f'\nЦена-источник: {number_format(price.source_value, decimal_pos=2)}'
    return format_html('<span class="text-nowrap" title="{}">{}</span>', hint, _money(price.value))


class ProductPriceColumn(tables.Column):
    """Расчётная цена одного типа. Цены берутся из предзагрузки prices
    (_base_queryset) — без неё это запрос на ячейку."""

    def __init__(self, price_type, **kwargs):
        self.price_type = price_type
        super().__init__(
            verbose_name=price_type.name, accessor='pk', orderable=False, empty_values=(),
            attrs={'th': {'class': 'text-end'}, 'td': {'class': 'col-num'}}, **kwargs)

    def render(self, record):
        price = next((p for p in record.prices.all() if p.price_type_id == self.price_type.pk), None)
        return product_price_html(price)


class ProductTable(tables.Table):
    """Товарная таблица: строка — Product, поставщики раскрываются под ней."""

    expand = tables.Column(verbose_name='', empty_values=(), orderable=False,
                           attrs={'th': {'class': 'col-expand'}, 'td': {'class': 'col-expand'}})
    # Бренд и категории — не отдельные колонки, а строка под названием: у товаров
    # без данных PIM (а это почти весь каталог, пока идёт бэкфилл) обе были бы
    # столбцами прочерков, отнимающими ширину у названия.
    display_name = tables.Column(verbose_name='Название', accessor='display_name', orderable=False,
                                 attrs={'td': {'class': 'col-name'}})
    # empty_values=() обязателен: иначе django-tables2 при number=NULL не
    # дойдёт до render_number вовсе, а тихо подставит свой дефолтный «—» —
    # ровно то, что скрывало number_fallback ниже (тот же приём уже нужен
    # prime_cost_range).
    number = tables.Column(verbose_name='Артикул', empty_values=(),
                           attrs={'td': {'class': 'col-number'}})
    supplier_count = tables.Column(verbose_name='Поставщиков', default='—',
                                   attrs={'th': {'class': 'text-end'}, 'td': {'class': 'col-num'}})
    prime_cost_range = tables.Column(
        verbose_name='Себестоимость', accessor='pk', orderable=False, empty_values=(),
        attrs={'th': {'class': 'text-end'}, 'td': {'class': 'col-num'}},
    )
    total_stock = tables.Column(verbose_name='Остаток', default=NO_STOCK_DATA,
                                attrs={'th': {'class': 'text-end'}, 'td': {'class': 'col-num'}})

    # Необязательные колонки — включаются в выборе колонок (product/columns.py).
    photo = tables.Column(verbose_name=COLUMN_LABELS['photo'], empty_values=(), orderable=False)
    tags = tables.Column(verbose_name=COLUMN_LABELS['tags'], empty_values=(), orderable=False)
    ean = tables.Column(verbose_name=COLUMN_LABELS['ean'], empty_values=(), orderable=False)
    pim_status = tables.Column(verbose_name=COLUMN_LABELS['pim_status'], empty_values=(),
                               orderable=False)

    class Meta:
        model = Product
        fields = ()
        sequence = (
            'expand', 'photo', 'display_name', 'number',
            'supplier_count', 'prime_cost_range', 'total_stock', 'tags', 'ean', 'pim_status',
        )
        attrs = {'class': 'table products-table align-middle mb-0'}
        row_attrs = {'class': 'product-row', 'data-product-pk': lambda record: record.pk}

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        selected = kwargs.pop('selected_columns', None) or DEFAULT_COLUMNS
        # Расчётные цены (product_pricing) — колонка на каждый тип цены с
        # show_on_page. Типы заводят менеджеры, поэтому колонки собираются
        # здесь, а не объявлены в классе; включает их флажок у типа, а не
        # выбор колонок.
        price_columns = [
            (f'price_{price_type.pk}', ProductPriceColumn(price_type))
            for price_type in ProductPriceType.objects.filter(show_on_page=True)
        ]
        sequence = list(self._meta.sequence)
        at = sequence.index('total_stock')
        kwargs['sequence'] = sequence[:at] + [key for key, _ in price_columns] + sequence[at:]
        super().__init__(*args, extra_columns=price_columns, **kwargs)
        for key in PRODUCT_ROW_COLUMNS:
            if key not in selected:
                self.columns.hide(key)

    def render_expand(self, record):
        """Кнопка раскрытия.

        Адрес лежит в data-атрибуте, а не в hx-get, и запрос делает скрипт
        через htmx.ajax(). С hx-get на кнопке HTMX ходил бы на КАЖДЫЙ клик,
        включая сворачивающий: строка честно пряталась, но следом приходил
        ответ и наполнял её заново — лишний запрос на каждое сворачивание и
        контент, живущий в скрытой строке. Видно это только в браузере: в
        тестах обе половины по отдельности проходят.
        """
        return format_html(
            '<button type="button" class="btn btn-sm btn-expand product-expand"'
            ' data-suppliers-url="{}" data-suppliers-target="#product-suppliers-{}"'
            ' aria-expanded="false"'
            ' aria-label="Показать поставщиков" title="Показать поставщиков">'
            '<i class="bi bi-chevron-right" aria-hidden="true"></i></button>',
            reverse('product-suppliers', kwargs={'pk': record.pk}),
            record.pk,
        )

    def render_number(self, value, record):
        """У части Product с number=NULL уже есть привязанный MainProduct с
        непустым sku (number_fallback, см. annotate_product_rows) — тогда
        строка не должна выглядеть так, будто артикула нет вовсе. Приглушён,
        как и «нет данных» в других колонках: это не настоящий Product.number,
        а то, что видно у поставщика.
        """
        if value:
            return value
        fallback = getattr(record, 'number_fallback', None)
        if fallback:
            return format_html(
                '<span class="text-body-tertiary" title="Артикул из привязанного поставщика, '
                'у самого товара он не заполнен">{}</span>', fallback)
        return format_html('<span class="text-body-tertiary">—</span>')

    def render_display_name(self, value, record):
        """Название и под ним — бренд и категории из PIM, если они уже есть.

        Там же метка «Набор» и у компонентов — «в N наборах» со ссылкой на
        эти наборы. set_totals и in_sets_count навешивает на строки страницы
        ProductPage.get_context_data (attach_set_info); без него — как у
        обычного товара.
        """
        meta = [record.brand.name] if record.brand else []
        meta += [category.name for category in record.categories.all()]
        parts = [format_html('{}', ' · '.join(meta))] if meta else []
        if getattr(record, 'set_totals', None):
            parts.insert(0, format_html('<span class="badge product-set-badge">Набор</span>'))
        in_sets = getattr(record, 'in_sets_count', 0)
        if in_sets:
            parts.append(format_html(
                '<a class="product-in-sets" href="{}?contains={}">{}</a>',
                reverse('products'), record.pk, in_sets_label(in_sets)))
        meta_html = (format_html('<div class="product-meta">{}</div>',
                                 format_html_join(' · ', '{}', ((part,) for part in parts)))
                     if parts else '')
        return format_html('<div class="product-name" title="{}">{}</div>{}', value, value, meta_html)

    def render_prime_cost_range(self, record):
        """Диапазон себестоимости по поставщикам товара.

        number_format, а не f'{:.2f}': интерфейс русский, и Django форматирует
        десятичные с запятой. Питоновское форматирование дало бы «99.00» рядом
        с «99,00» в соседней таблице поставщиков.
        """
        low = getattr(record, 'min_prime_cost', None)
        high = getattr(record, 'max_prime_cost', None)
        if low is None and high is None:
            own = format_html('<span class="text-body-tertiary">{}</span>', '—')
        elif low == high:
            own = _money(low)
        else:
            own = format_html('<span class="text-nowrap">{} – {}</span>', _money(low), _money(high))
        totals = getattr(record, 'set_totals', None)
        if not totals:
            return own
        return format_html('{}<div class="set-cost-hint">из компл.: {}</div>', own, set_cost_html(totals))

    def render_total_stock(self, record):
        """NULL и 0 — разные вещи.

        NULL означает «остаток ни разу не синхронизировался», 0 — «синхронизи-
        ровался и его нет». Sum() по пустому множеству тоже даёт NULL.
        """
        total = getattr(record, 'total_stock', None)
        if total is None:
            return format_html('<span class="text-body-tertiary">{}</span>', NO_STOCK_DATA)
        if total > 0:
            return format_html('<span class="stock-in">{}</span>', total)
        return format_html('<span class="text-body-tertiary">{}</span>', total)

    # --- необязательные колонки из данных PIM -------------------------------

    def render_photo(self, record):
        """Фото товара — ссылка на наш прокси; отрисовка в сеть не ходит.

        Прямая ссылка на PIM не годится: PIM отдаёт картинки только с токеном,
        и браузер получал 401 (см. main_product_manager.utils.fetch_pim_image).
        За байтами в PIM ходит уже прокси — по запросу <img>, с кэшем на сутки.
        Колонка по-прежнему выключена по умолчанию: на холодном кэше каждое
        фото — два запроса к PIM через воркер приложения.

        data-zoom-src — крупный размер для увеличения при наведении (скрипт в
        product/list.html). Его грузит только наведение, а не отрисовка
        страницы.
        """
        from main_product_manager.utils import pim_image_url

        data = record.raw_data or {}
        file_id = data.get('mainImageId') or data.get('imageId')
        url = pim_image_url(file_id)
        if not url:
            return '—'
        return format_html(
            '<img src="{}" data-zoom-src="{}" alt="" class="product-photo"'
            ' style="max-height:50px;max-width:80px;object-fit:contain" loading="lazy">',
            url, pim_image_url(file_id, 'large'),
        )

    def render_tags(self, record):
        return ', '.join((record.raw_data or {}).get('tag') or []) or '—'

    def render_ean(self, record):
        return (record.raw_data or {}).get('ean') or '—'

    def render_pim_status(self, record):
        return (record.raw_data or {}).get('status') or '—'


class SupplierRowTable(tables.Table):
    """Строки поставщиков под товаром — то, чем была вся таблица старой главной.

    Колонки выбирает пользователь (product/columns.py). Объявлены здесь только
    те, что требуют своей отрисовки; остальные — простые поля MainProduct и
    его поставщика — собираются в __init__ из каталога.
    """

    actions = tables.Column(verbose_name='', empty_values=(), orderable=False)
    name = tables.Column(verbose_name=COLUMN_LABELS['name'])
    stock = tables.Column(verbose_name=COLUMN_LABELS['stock'], empty_values=())
    # Единственная колонка, которой разрешён перенос строк: сообщение о наличии
    # у поставщиков бывает в целое предложение. Остальные ячейки — в одну строку.
    stock_msg = tables.Column(verbose_name=COLUMN_LABELS['stock_msg'], empty_values=(),
                              attrs={'td': {'class': 'col-wrap'}})
    delivery_days = tables.Column(verbose_name=COLUMN_LABELS['delivery_days'], empty_values=())

    DECLARED = ('actions', 'name', 'stock', 'stock_msg', 'delivery_days')

    class Meta:
        model = MainProduct
        fields = ()
        orderable = False
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-sm align-middle mb-0 suppliers-table'}

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        selected = [key for key in (kwargs.pop('selected_columns', None) or DEFAULT_COLUMNS)
                    if key in SUPPLIER_ROW_COLUMNS]
        # Выбраны только колонки строки товара — таблица поставщиков не должна
        # остаться вовсе без колонок.
        if not selected:
            selected = [key for key in DEFAULT_COLUMNS if key in SUPPLIER_ROW_COLUMNS]
        extra_columns = [
            (key, tables.Column(accessor=key, verbose_name=COLUMN_LABELS[key], default='—'))
            for key in selected if key not in self.DECLARED
        ]
        kwargs['exclude'] = [key for key in self.DECLARED if key not in selected]
        kwargs['sequence'] = selected
        super().__init__(*args, extra_columns=extra_columns, **kwargs)

    def render_actions(self, record):
        return render_to_string('product/partials/supplier_row_actions.html',
                                {'record': record}, request=self.request)

    def render_name(self, record):
        return format_html('<a href="{}">{}</a>',
                           reverse('mainproduct-info', kwargs={'pk': record.pk}), record.name)

    def render_stock(self, record):
        """NULL — «ни разу не синхронизировался», 0 — «синхронизировался, нет»."""
        return NO_STOCK_DATA if record.stock is None else record.stock

    def render_stock_msg(self, record):
        # Остаток проверяется ПЕРЕД поставщиком: «Нет данных» — утверждение про
        # остаток, и строка без поставщика с NULL в остатке про него тоже ничего
        # не знает. Так же было на старой главной.
        if record.stock is None:
            return NO_STOCK_DATA
        if not record.supplier:
            return ''
        if record.stock == 0:
            return record.supplier.msg_navailable or ''
        return record.supplier.msg_available or ''

    def render_delivery_days(self, record):
        # Срок физически берётся из полей поставщика — без него его неоткуда
        # взять, отсюда и расхождение с render_stock_msg.
        if not record.supplier:
            return ''
        days = record.supplier.get_delivery_days_for_stock(record.stock)
        return '' if days is None else days
