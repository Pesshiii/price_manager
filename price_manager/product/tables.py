import django_tables2 as tables
from django.db.models import Count, Max, Min, Q, Sum
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import number_format
from django.utils.html import format_html

from main_product_manager.models import MainProduct

from .columns import COLUMN_LABELS, DEFAULT_COLUMNS, PRODUCT_ROW_COLUMNS, SUPPLIER_ROW_COLUMNS
from .models import Product

# Ровно эта строка, когда остаток не синхронизировался ни разу: NULL в stock —
# третье состояние, а не ноль.
NO_STOCK_DATA = 'Нет данных'


def _money(value):
    """Цена в ячейке; ноль приглушён — он чаще значит «цены нет», чем «бесплатно»."""
    text = number_format(value, decimal_pos=2)
    if not value:
        return format_html('<span class="text-body-tertiary">{}</span>', text)
    return format_html('{}', text)


def annotate_product_rows(queryset):
    """Агрегаты по связанным MainProduct для строки товара.

    Настоящая агрегация по Product.main_products, а не оконные функции. Старая
    главная считала то же самое окнами (grouping.py, удалён в Phase 2b) только
    потому, что её корнем был плоский MainProduct и группы приходилось
    изображать. Здесь группа это строка, поэтому окна не нужны.

    distinct=True у Count обязателен: параллельно висит join на categories из
    фильтра, и без него поставщики посчитались бы с кратностью категорий.
    """
    return queryset.annotate(
        supplier_count=Count('main_products__supplier', distinct=True),
        total_stock=Sum('main_products__stock'),
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
    )


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
        super().__init__(*args, **kwargs)
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
        """Название и под ним — бренд и категории из PIM, если они уже есть."""
        meta = [record.brand.name] if record.brand else []
        meta += [category.name for category in record.categories.all()]
        meta_html = format_html('<div class="product-meta">{}</div>', ' · '.join(meta)) if meta else ''
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
            return format_html('<span class="text-body-tertiary">{}</span>', '—')
        if low == high:
            return _money(low)
        return format_html('<span class="text-nowrap">{} – {}</span>', _money(low), _money(high))

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
        """
        from main_product_manager.utils import pim_image_url

        data = record.raw_data or {}
        url = pim_image_url(data.get('mainImageId') or data.get('imageId'))
        if not url:
            return '—'
        return format_html(
            '<img src="{}" alt="" style="max-height:50px;max-width:80px;object-fit:contain"'
            ' loading="lazy">',
            url,
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
