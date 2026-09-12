"""Схлопывание MainProduct с общим товаром PIM в строку-представитель на главной.

Несколько MainProduct законно делят один product — это всегда записи разных
поставщиков (см. docstring sync_pim_relations в utils.py). На главной такие
записи показываются одной строкой-заголовком, а сами становятся скрытыми
строками-членами под ней.

Всё, что показывает заголовок, считается оконными функциями на queryset, а не
пост-обработкой в Python: иначе по этим значениям нельзя отсортировать, а
сортировка колонок на главной сохраняется. Оконная аннотация одинакова у всех
строк партиции, поэтому неважно, чья именно запись стала носителем заголовка.
"""

from django.db.models import (
    Case,
    Count,
    F,
    IntegerField,
    Max,
    Min,
    TextField,
    Value,
    When,
    Window,
)
from django.db.models.functions import Cast, Coalesce, Concat, FirstValue, RowNumber

# Ценовые колонки, участвующие в поколоночном сквозном выборе по price_priority.
# Три колонки supplier_product_* сюда НЕ входят: это коррелированные Subquery из
# MainProductTableView.get_table_data, а не поля модели, и на заголовке они
# показывают «—» — настоящие значения видны только на строках-членах.
GROUPED_PRICE_COLUMNS = (
    'prime_cost',
    'wholesale_price',
    'basic_price',
    'm_price',
    'wholesale_price_extra',
    'discount_price',
    'kaspi_price',
)

# Колонки, которым для отрисовки нужен выбор остатка по stock_priority.
STOCK_COLUMNS = ('stock', 'stock_msg', 'delivery_days')

# Ровно эта строка, когда остаток не синхронизировался ни разу: NULL в stock —
# третье состояние, а не ноль.
NO_STOCK_DATA = 'Нет данных'


def group_key():
    """Ключ партиции — по FK на product.Product, а не по join к его pim_id.

    В SQL все NULL в PARTITION BY равны друг другу, поэтому голый product_id
    собрал бы все непривязанные товары в одну фальшивую группу. Непривязанная
    строка падает на собственный id и попадает в партицию из самой себя,
    grp_size = 1, заголовок не рисуется. Случая пустой строки больше нет: FK
    бывает только числом или NULL.

    Обе ветки ОБЯЗАНЫ быть с префиксом. Это два разных пространства
    целочисленных PK, и без префикса product_id = 42 и MainProduct.id = 42
    дают одинаковый ключ — непривязанный товар молча уезжает в чужую группу.
    Старая версия жила без префикса только потому, что pim_id — строка, не
    похожая на маленькое целое.

    Case/When, а не Coalesce поверх Concat: postgres-овый CONCAT() считает
    NULL пустой строкой (в отличие от оператора ||), поэтому
    Concat('pim-', NULL) даёт 'pim-', а не NULL — Coalesce никогда не
    доходил бы до второй ветки, и ВСЕ непривязанные товары склеивались бы в
    одну группу с ключом 'pim-'. Ровно та фальшивая группа, от которой этот
    ключ и должен защищать.
    """
    return Case(
        When(
            product__isnull=True,
            then=Concat(Value('mp-'), Cast('id', TextField()), output_field=TextField()),
        ),
        default=Concat(Value('pim-'), Cast('product_id', TextField()), output_field=TextField()),
        output_field=TextField(),
    )


def _tier(priority_field):
    """Ярус выбора члена группы: проранжирован / без приоритета / без поставщика."""
    return Case(
        When(supplier__isnull=True, then=Value(2)),
        When(**{f'supplier__{priority_field}__isnull': True}, then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )


def _priority(priority_field):
    """Значение приоритета; NULL уже разведены по ярусам, так что 0 безопасен."""
    return Coalesce(f'supplier__{priority_field}', Value(0), output_field=IntegerField())


def _member_order(kind):
    """Порядок выбора члена группы: ярус → приоритет → наименьший id."""
    return [F(f'grp_{kind}_tier'), F(f'grp_{kind}_priority'), F('id')]


def _nulls_last(column):
    """`(X IS NULL)` первым ключом — у оконных функций Postgres нет IGNORE NULLS."""
    return Case(
        When(**{f'{column}__isnull': True}, then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )


def first_non_null(column, kind):
    """Значение колонки у первого члена группы, у которого оно не NULL."""
    return Window(
        FirstValue(column),
        partition_by=[F('grp_key')],
        order_by=[_nulls_last(column), *_member_order(kind)],
    )


def annotate_groups(queryset, selected_columns, searching=False):
    """Навесить оконные аннотации группы pim_id.

    Вызывать строго после дедупликации и после Subquery-аннотаций: join по M2M
    категорий дублирует строки, а Postgres считает оконные функции раньше
    DISTINCT, поэтому по недедуплицированному queryset Count(*) OVER раздует
    размер группы.
    """
    queryset = queryset.annotate(
        grp_key=group_key(),
        grp_price_tier=_tier('price_priority'),
        grp_price_priority=_priority('price_priority'),
        grp_stock_tier=_tier('stock_priority'),
        grp_stock_priority=_priority('stock_priority'),
    )

    # Порядок членов внутри группы. С поиском — по убыванию релевантности, чтобы
    # выдача не теряла смысл; без поиска — по приоритету поставщика. Заголовок
    # определён как grp_seq == 1, а не как заранее выбранная запись, поэтому он
    # остаётся первой строкой группы в обоих режимах.
    seq_order = [F('rank').desc(), *_member_order('price')] if searching else _member_order('price')

    annotations = {
        'grp_size': Window(Count('id'), partition_by=[F('grp_key')]),
        'grp_seq': Window(RowNumber(), partition_by=[F('grp_key')], order_by=seq_order),
        'grp_min_id': Window(Min('id'), partition_by=[F('grp_key')]),
    }
    if searching:
        annotations['grp_max_rank'] = Window(Max('rank'), partition_by=[F('grp_key')])

    for column in GROUPED_PRICE_COLUMNS:
        if column in selected_columns:
            annotations[f'grp_{column}'] = first_non_null(column, 'price')

    if any(column in selected_columns for column in STOCK_COLUMNS):
        annotations['grp_stock'] = first_non_null('stock', 'stock')
        # Статус наличия и срок поставки считаются от поставщика того члена,
        # чей остаток победил, — а не от поставщика носителя заголовка.
        for alias, field in (
            ('grp_msg_available', 'supplier__msg_available'),
            ('grp_msg_navailable', 'supplier__msg_navailable'),
            ('grp_delivery_available', 'supplier__delivery_days_available'),
            ('grp_delivery_navailable', 'supplier__delivery_days_navailable'),
        ):
            annotations[alias] = Window(
                FirstValue(field),
                partition_by=[F('grp_key')],
                order_by=[_nulls_last('stock'), *_member_order('stock')],
            )

    return queryset.annotate(**annotations)


def order_groups(queryset, searching=False):
    """Порядок строк по умолчанию.

    Без поиска группа встаёт на место своего члена с наименьшим id, поэтому
    сегодняшний порядок (Meta.ordering = ['id']) для несгруппированных строк не
    двигается. С поиском — на место лучшего совпадения.
    """
    if searching:
        return queryset.order_by('-grp_max_rank', 'grp_key', 'grp_seq')
    return queryset.order_by('grp_min_id', 'grp_key', 'grp_seq')


def order_by_group(queryset, accessor, descending):
    """Сортировка по колонке, не разваливающая группы.

    Групповые ключи дописываются ПОСЛЕ ключа значения и сами не переворачиваются
    — иначе на втором клике (по убыванию) заголовок оказался бы последней
    строкой своей группы, под членами, которых он представляет. Ключ значения
    обязан быть постоянным внутри партиции, иначе члены разъедутся; для ценовых
    колонок это ровно то значение, которое показывает заголовок.

    Возвращает `(queryset, modified)` в контракте django-tables2: `modified=True`
    заставляет TableQuerysetData.order_by отдать упорядочивание нам целиком,
    минуя переворот всего кортежа order_by.
    """
    annotations = getattr(getattr(queryset, 'query', None), 'annotations', None)
    if not annotations or 'grp_key' not in annotations:
        return queryset, False

    alias = f'grp_{accessor}'
    if alias not in annotations:
        alias = f'grpord_{accessor}'
        if alias not in annotations:
            queryset = queryset.annotate(**{alias: first_non_null(accessor, 'price')})

    key = F(alias).desc(nulls_last=True) if descending else F(alias).asc(nulls_last=True)
    return queryset.order_by(key, 'grp_key', 'grp_seq'), True


def is_group_head(record):
    """Открывает ли строка группу — то есть надо ли рисовать над ней заголовок."""
    return getattr(record, 'grp_size', 1) > 1 and getattr(record, 'grp_seq', None) == 1


def is_group_member(record):
    """Входит ли строка в группу (и потому рендерится скрытой)."""
    return getattr(record, 'grp_size', 1) > 1


class GroupHeadRecord:
    """Псевдо-запись строки-заголовка группы pim_id.

    Не модель намеренно: заголовок не должен показывать собственные значения
    того члена, от которого он взят, — по нему нельзя ни обновить товар, ни
    понять, чей это поставщик. Любой не выставленный здесь атрибут отдаётся как
    None, поэтому колонка падает на table-wide default django-tables2 («—»), и
    добавление новой колонки в таблицу не требует правки заголовка.

    В queryset ничего синтетического при этом не кладётся: объект живёт только
    на время рендера строки.
    """

    is_group_head = True

    def __init__(self, record, price_columns=GROUPED_PRICE_COLUMNS):
        self.pk = record.pk
        self.id = record.pk
        # Локальный id зеркала, а не pim_id из PIM: последний потребовал бы
        # join к product.Product в каждом запросе главной (78 мс против 580 —
        # см. комментарий в MainProductTableView.get_table_data) ради строки,
        # которую ни один шаблон не рисует. __str__ — отладочный.
        self.product_id = record.product_id
        self.grp_key = record.grp_key
        self.grp_size = record.grp_size
        # Остаток и всё, что от него считается, — от победителя по stock_priority.
        self.stock = getattr(record, 'grp_stock', None)
        self.grp_msg_available = getattr(record, 'grp_msg_available', None)
        self.grp_msg_navailable = getattr(record, 'grp_msg_navailable', None)
        self.grp_delivery_available = getattr(record, 'grp_delivery_available', None)
        self.grp_delivery_navailable = getattr(record, 'grp_delivery_navailable', None)
        # Цены — поколоночно, каждая от своего первого непустого члена.
        for column in price_columns:
            setattr(self, column, getattr(record, f'grp_{column}', None))

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return None

    def __str__(self):
        return f'Группа PIM {self.product_id}'
