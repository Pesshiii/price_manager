import django_tables2 as tables
from django.db.models import Count, Max, Min, Q, Sum
from django.urls import reverse
from django.utils.formats import number_format
from django.utils.html import format_html

from .models import Product

# Ровно эта строка, когда остаток не синхронизировался ни разу: NULL в stock —
# третье состояние, а не ноль. Та же константа и та же причина, что в
# main_product_manager/grouping.py.
NO_STOCK_DATA = 'Нет данных'


def annotate_product_rows(queryset):
    """Агрегаты по связанным MainProduct для строки товара.

    Настоящая агрегация по Product.main_products, а не оконные функции.
    grouping.py в main_product_manager считает то же самое окнами только потому,
    что там корень выборки — плоский MainProduct и группы приходится
    изображать. Здесь группа это строка, поэтому окна не нужны — и переносить
    их сюда не надо.

    distinct=True у Count обязателен: параллельно висит join на categories из
    фильтра, и без него поставщики посчитались бы с кратностью категорий.
    """
    return queryset.annotate(
        supplier_count=Count('main_products__supplier', distinct=True),
        total_stock=Sum('main_products__stock'),
        min_prime_cost=Min('main_products__prime_cost'),
        max_prime_cost=Max('main_products__prime_cost'),
        in_stock_count=Count('main_products', filter=Q(main_products__stock__gt=0), distinct=True),
    )


class ProductTable(tables.Table):
    """Товарная таблица: строка — Product, поставщики раскрываются под ней."""

    expand = tables.Column(verbose_name='', empty_values=(), orderable=False)
    display_name = tables.Column(verbose_name='Название', accessor='display_name', orderable=False)
    number = tables.Column(verbose_name='Артикул')
    brand = tables.Column(verbose_name='Бренд', default='—')
    product_categories = tables.Column(
        verbose_name='Категории', accessor='pk', orderable=False, empty_values=(),
    )
    supplier_count = tables.Column(verbose_name='Поставщиков', default='—')
    prime_cost_range = tables.Column(
        verbose_name='Себестоимость', accessor='pk', orderable=False, empty_values=(),
    )
    total_stock = tables.Column(verbose_name='Остаток', default=NO_STOCK_DATA)

    class Meta:
        model = Product
        fields = ()
        sequence = (
            'expand', 'display_name', 'number', 'brand', 'product_categories',
            'supplier_count', 'prime_cost_range', 'total_stock',
        )
        attrs = {'class': 'table table-hover align-middle'}
        row_attrs = {'data-product-pk': lambda record: record.pk}

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

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
            '<button type="button" class="btn btn-sm btn-outline-secondary product-expand"'
            ' data-suppliers-url="{}" data-suppliers-target="#product-suppliers-{}"'
            ' aria-expanded="false"'
            ' aria-label="Показать поставщиков" title="Показать поставщиков">'
            '<i class="bi bi-chevron-down"></i></button>',
            reverse('product-suppliers', kwargs={'pk': record.pk}),
            record.pk,
        )

    def render_product_categories(self, record):
        names = [c.name for c in record.categories.all()]
        return ', '.join(names) if names else '—'

    def render_prime_cost_range(self, record):
        """Диапазон себестоимости по поставщикам товара.

        number_format, а не f'{:.2f}': интерфейс русский, и Django форматирует
        десятичные с запятой. Питоновское форматирование дало бы «99.00» рядом
        с «99,00» в соседней таблице поставщиков.
        """
        low = getattr(record, 'min_prime_cost', None)
        high = getattr(record, 'max_prime_cost', None)
        if low is None and high is None:
            return '—'
        if low == high:
            return number_format(low, decimal_pos=2)
        return f'{number_format(low, decimal_pos=2)} — {number_format(high, decimal_pos=2)}'

    def render_total_stock(self, record):
        """NULL и 0 — разные вещи.

        NULL означает «остаток ни разу не синхронизировался», 0 — «синхронизи-
        ровался и его нет». Sum() по пустому множеству тоже даёт NULL.
        """
        total = getattr(record, 'total_stock', None)
        if total is None:
            return NO_STOCK_DATA
        return total
