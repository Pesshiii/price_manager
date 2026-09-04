DEFAULT_VISIBLE_COLUMNS = [
  'actions',
  'article',
  'supplier',
  'name',
  'manufacturer',
  'prime_cost',
  'stock',
  'delivery_days',
  'stock_msg',
  'pim_photo',
]

AVAILABLE_COLUMN_GROUPS = [
  (
    'Главный прайс',
    [
      ('actions', 'Действия'),
      ('sku', 'Артикул товара'),
      ('article', 'Артикул поставщика'),
      ('name', 'Название'),
      ('description', 'Описание'),
      ('supplier', 'Поставщик'),
      ('manufacturer', 'Производитель'),
      ('categories', 'Категории'),
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
      ('weight', 'Вес'),
      ('length', 'Длина'),
      ('width', 'Ширина'),
      ('depth', 'Глубина'),
      ('price_updated_at', 'Последнее обновление цены'),
      ('stock_updated_at', 'Последнее обновление остатка'),
    ],
  ),
  (
    'Поставщик',
    [
      ('supplier__name', 'Поставщик • Название'),
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
  (
    'Производитель и категория',
    [
      ('manufacturer__name', 'Производитель • Название'),
    ],
  ),
  (
    'PIM',
    [
      ('pim_photo', 'PIM • Фото'),
      ('pim_name', 'PIM • Название'),
      ('pim_number', 'PIM • Номер'),
      ('pim_categories', 'PIM • Категории'),
      ('pim_tags', 'PIM • Теги'),
      ('pim_brand', 'PIM • Бренд'),
      ('pim_ean', 'PIM • EAN'),
      ('pim_status', 'PIM • Статус'),
    ],
  ),
]

ORDERED_COLUMNS = [
    ('actions', 'Действия'),
    ('pim_photo', 'PIM • Фото'),
    ('article', 'Артикул поставщика'),
    ('name', 'Название'),
]
AVAILABLE_COLUMN_CHOICES = ORDERED_COLUMNS + [item for _, options in AVAILABLE_COLUMN_GROUPS for item in options if not item in ORDERED_COLUMNS]
AVAILABLE_COLUMN_MAP = dict(AVAILABLE_COLUMN_CHOICES)
