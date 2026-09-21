"""Выбор колонок на товарной странице — перенос со старой главной.

Колонки двух уровней, и выбираются они одним списком:

- «Товар» — строка Product. Её обязательные колонки (название, номер, бренд,
  категории, поставщики, себестоимость, остаток) не выбираются; здесь только
  необязательные, из данных PIM.
- «Строки поставщиков» и «Поставщик» — таблица MainProduct, которая
  раскрывается под товаром. Это то, что на старой главной было всей таблицей.

Чего нет по сравнению со старой главной, и почему:
- description, manufacturer, categories, weight, length, width, depth
  MainProduct — Phase 2 их удаляет (D13, D1). Бренд и категории показывает
  строка товара.
- «PIM • Название / Номер / Категории / Бренд» — это обязательные колонки
  строки товара.

Предпочтения хранятся под СВОИМ ключом, а не под ключом старой главной: там
лежат списки с manufacturer и прочими полями, которые Phase 2 удаляет. Чужой
ключ принёс бы их сюда; normalize_columns их бы и отбросил, но незачем
полагаться на это для данных, которые ни разу здесь не выбирались.
"""
from django.core.cache import cache

PRODUCT_COLUMN_GROUPS = [
    (
        'Товар',
        [
            ('photo', 'Фото'),
            ('tags', 'Теги'),
            ('ean', 'EAN'),
            ('pim_status', 'Статус в PIM'),
        ],
    ),
    (
        'Строки поставщиков',
        [
            ('actions', 'Действия'),
            ('supplier', 'Поставщик'),
            ('article', 'Артикул поставщика'),
            ('sku', 'Артикул товара'),
            ('name', 'Название у поставщика'),
            ('stock', 'Остаток'),
            ('stock_msg', 'Статус наличия'),
            ('delivery_days', 'Срок поставки (Рабочие дни)'),
            ('prime_cost', 'Себестоимость'),
            ('wholesale_price', 'Оптовая цена'),
            ('basic_price', 'Базовая цена'),
            ('m_price', 'Цена ИМ'),
            ('kaspi_price', 'Цена Каспи'),
            ('wholesale_price_extra', 'Оптовая цена доп.'),
            ('discount_price', 'Цена со скидкой'),
            ('supplier_product_price', 'Цена поставщика'),
            ('supplier_product_rrp', 'РРЦ'),
            ('supplier_product_discount_price', 'Цена поставщика со скидкой'),
            ('price_updated_at', 'Последнее обновление цены'),
            ('stock_updated_at', 'Последнее обновление остатка'),
        ],
    ),
    (
        'Поставщик',
        [
            ('supplier__currency__name', 'Поставщик • Валюта'),
            ('supplier__price_updated_at', 'Поставщик • Обновление цены'),
            ('supplier__stock_updated_at', 'Поставщик • Обновление остатков'),
            ('supplier__delivery_days', 'Поставщик • Срок доставки'),
            ('supplier__delivery_days_available', 'Поставщик • Срок поставки при наличии'),
            ('supplier__delivery_days_navailable', 'Поставщик • Срок поставки при отсутствии'),
            ('supplier__price_update_rate', 'Поставщик • Частота обновления цен'),
            ('supplier__stock_update_rate', 'Поставщик • Частота обновления остатков'),
            ('supplier__msg_available', 'Поставщик • Сообщение при наличии'),
            ('supplier__msg_navailable', 'Поставщик • Сообщение при отсутствии'),
        ],
    ),
]

PRODUCT_ROW_COLUMNS = [key for key, _ in PRODUCT_COLUMN_GROUPS[0][1]]
SUPPLIER_ROW_COLUMNS = [key for _, choices in PRODUCT_COLUMN_GROUPS[1:] for key, _ in choices]
COLUMN_LABELS = {key: label for _, choices in PRODUCT_COLUMN_GROUPS for key, label in choices}

# То, что строки поставщиков показывали до переноса, плюс то, что старая
# главная показывала по умолчанию: действия, статус наличия, срок поставки.
# Фото по умолчанию выключено — см. ProductTable.render_photo. Порядок —
# каталожный, как и у любого сохранённого выбора (см. normalize_columns).
_DEFAULT = {
    'actions', 'supplier', 'article', 'sku', 'prime_cost', 'basic_price', 'm_price',
    'stock', 'stock_msg', 'delivery_days',
}
DEFAULT_COLUMNS = [key for key in COLUMN_LABELS if key in _DEFAULT]

_CACHE_TTL = 60 * 60 * 24 * 30  # 30 дней, как у старой главной


def _cache_key(user_id: int) -> str:
    return f'product_page:columns:user:{user_id}'


def normalize_columns(columns) -> list[str]:
    """Только известные колонки, в порядке каталога; пустой выбор — дефолт.

    Порядок каталога, а не порядок в запросе: чекбоксы шлются в порядке DOM,
    но кэш переживает правки каталога, и колонки не должны прыгать местами от
    того, в какой момент человек их отметил.
    """
    chosen = set(columns or [])
    normalized = [key for key in COLUMN_LABELS if key in chosen]
    return normalized or list(DEFAULT_COLUMNS)


def load_columns(user) -> list[str]:
    if not user.is_authenticated:
        return list(DEFAULT_COLUMNS)
    return normalize_columns(cache.get(_cache_key(user.id)))


def save_columns(user, columns) -> list[str]:
    normalized = normalize_columns(columns)
    if user.is_authenticated:
        cache.set(_cache_key(user.id), normalized, _CACHE_TTL)
    return normalized
