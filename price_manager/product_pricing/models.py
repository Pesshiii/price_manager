"""Наценки на уровне товара (product.Product), а не строки поставщика.

Второй уровень ценообразования рядом с product_price_manager:

- product_price_manager — правила на поставщика, пишут цены в MainProduct;
- здесь — правила на товар: берут основную цену Product (сведённую по
  поставщикам, см. product/services/prices.py) и считают из неё расчётные цены
  своих типов. Цены Product и MainProduct они не трогают — результат лежит
  отдельно, в ProductPrice, вместе с правилом, которое его дало.

Типы расчётных цен заводятся в интерфейсе (ProductPriceType), а не
перечислены в коде: «розничная», «для маркетплейса» и т. п. — решение
менеджеров, а не миграции.
"""
from decimal import ROUND_CEILING, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.formats import number_format

from main_product_manager.models import MP_PRICES
from product.models import SUPPLIER_PRICE_FIELDS

# Основные цены Product, от которых может считать правило, — сгруппированы так,
# как их знают менеджеры: из главного прайса (ГП) и из прайса поставщика (ПП).
SOURCE_FIXED = 'fixed_price'
GP_SOURCES = [
    ('prime_cost', 'Себестоимость'),
    ('wholesale_price', 'Оптовая цена'),
    ('wholesale_price_extra', 'Оптовая цена доп.'),
    ('basic_price', 'Базовая цена'),
    ('m_price', 'Цена ИМ'),
    ('kaspi_price', 'Цена Каспи'),
    ('discount_price', 'Цена со скидкой'),
]
PP_SOURCES = [
    ('supplier_price', 'Цена поставщика'),
    ('rrp', 'РРЦ'),
    ('supplier_discount_price', 'Цена поставщика со скидкой'),
]
SOURCE_CHOICES = [
    ('Главный прайс (ГП)', GP_SOURCES),
    ('Прайс поставщика (ПП), в тенге', PP_SOURCES),
    ('Без источника', [(SOURCE_FIXED, 'Фиксированная цена')]),
]
SOURCE_LABELS = dict(GP_SOURCES + PP_SOURCES + [(SOURCE_FIXED, 'Фиксированная цена')])
SOURCE_PRICES = [key for key, _ in GP_SOURCES + PP_SOURCES]
assert set(SOURCE_PRICES) == set(MP_PRICES) | set(SUPPLIER_PRICE_FIELDS), \
    'источники наценок должны совпадать с основными ценами Product'


def money(value) -> str:
    """«1 250», «12,50» — без лишних нулей после запятой, с разрядами."""
    if value is None:
        return '—'
    value = Decimal(value)
    decimals = 0 if value == value.to_integral_value() else 2
    return number_format(value, decimal_pos=decimals, force_grouping=True)


def _listed(what, names, limit=3):
    shown = ', '.join(names[:limit])
    rest = len(names) - limit
    return f'{what}: {shown}' + (f' и ещё {rest}' if rest > 0 else '')


class ProductPriceType(models.Model):
    """Вид расчётной цены товара — то, что считают наценки и показывает «Товары»."""

    name = models.CharField('Название', max_length=100, unique=True)
    pim_field = models.CharField(
        'Поле в PIM', max_length=100, blank=True, default='',
        help_text='Имя поля PriceManagerProduct в PIM, куда отправлять эту цену. '
                  'Пусто — в PIM не отправляется. Поле должно быть заведено в PIM.')
    show_on_page = models.BooleanField('Показывать на странице «Товары»', default=True)
    sorting = models.IntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Тип цены товара'
        verbose_name_plural = 'Типы цен товара'
        ordering = ['sorting', 'name']

    def __str__(self) -> str:
        return self.name


class ProductPriceRuleQuerySet(models.QuerySet):
    def in_effect(self, now=None):
        """Включённые правила, чей период действия идёт сейчас."""
        now = now or timezone.now()
        return self.filter(is_active=True).filter(
            models.Q(date_from__isnull=True) | models.Q(date_from__lte=now),
            models.Q(date_to__isnull=True) | models.Q(date_to__gte=now),
        )


class ProductPriceRule(models.Model):
    """Наценка на товар: цена-источник Product → расчётная цена типа price_type.

    Отбор товаров — все условия вместе (И): конкретные товары, категории (с
    подкатегориями), бренды, «только наборы», диапазон цены-источника.
    Пустое условие — не ограничивает.

    Если товару подходят несколько правил одного типа цены, действует одно —
    с меньшим «Приоритетом», при равном — созданное раньше. Правила не
    складываются: иначе итог зависел бы от того, сколько правил случайно
    накрыло товар.
    """

    name = models.CharField('Название', max_length=255)
    price_type = models.ForeignKey(
        ProductPriceType, on_delete=models.PROTECT, related_name='rules', verbose_name='Какую цену считать')
    source = models.CharField('От какой цены считать', max_length=32, choices=SOURCE_CHOICES,
                              default='prime_cost')
    categories = models.ManyToManyField(
        'product.Category', related_name='price_rules', blank=True, verbose_name='Категории',
        help_text='Вместе с подкатегориями. Пусто — все категории, включая товары без категории.')
    brands = models.ManyToManyField(
        'product.Brand', related_name='price_rules', blank=True, verbose_name='Бренды',
        help_text='Пусто — все бренды, включая товары без бренда.')
    # Наценка на конкретные товары — заводится с карточки товара. Обычное
    # условие, как категории: складывается с остальными по И.
    products = models.ManyToManyField(
        'product.Product', related_name='price_rules', blank=True, verbose_name='Товары',
        help_text='Только эти товары. Пусто — любые.')
    only_sets = models.BooleanField(
        'Только наборы', default=False,
        help_text='Только товары с составом набора из PIM (product.ProductSetItem).')
    price_from = models.DecimalField('Цена от', max_digits=20, decimal_places=2, null=True, blank=True,
                                     validators=[MinValueValidator(0)],
                                     help_text='Диапазон цены-источника, включительно.')
    price_to = models.DecimalField('Цена до', max_digits=20, decimal_places=2, null=True, blank=True,
                                   validators=[MinValueValidator(0)])
    date_from = models.DateTimeField('Дата начала', null=True, blank=True)
    date_to = models.DateTimeField('Дата окончания', null=True, blank=True)
    markup = models.DecimalField('Наценка, %', max_digits=7, decimal_places=2, default=0,
                                 validators=[MinValueValidator(-100)])
    increase = models.DecimalField('Надбавка, тг', max_digits=20, decimal_places=2, default=0)
    fixed_price = models.DecimalField('Фиксированная цена, тг', max_digits=20, decimal_places=2,
                                      null=True, blank=True, validators=[MinValueValidator(0)])
    rounding = models.DecimalField(
        'Округлять вверх до', max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Шаг округления вверх: 1, 10, 100… Пусто — без округления.')
    priority = models.PositiveIntegerField(
        'Приоритет', default=100,
        help_text='Меньше — важнее. Из нескольких подходящих правил одного типа цены действует одно.')
    is_active = models.BooleanField('Включено', default=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Изменено', auto_now=True)

    objects = ProductPriceRuleQuerySet.as_manager()

    class Meta:
        verbose_name = 'Наценка на товар'
        verbose_name_plural = 'Наценки на товар'
        ordering = ['price_type__sorting', 'price_type__name', 'priority', 'pk']

    def __str__(self) -> str:
        return self.name

    @property
    def is_fixed(self) -> bool:
        return self.source == SOURCE_FIXED

    def clean(self):
        errors = {}
        if self.is_fixed and self.fixed_price is None:
            errors['fixed_price'] = 'Укажите фиксированную цену.'
        if (self.price_from is not None and self.price_to is not None
                and self.price_from > self.price_to):
            errors['price_to'] = '«Цена до» меньше «Цены от».'
        if self.date_from and self.date_to and self.date_from > self.date_to:
            errors['date_to'] = 'Дата окончания раньше даты начала.'
        if errors:
            raise ValidationError(errors)

    def get_source_display(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    def formula_label(self) -> str:
        """«Себестоимость + 35 % + 100 тг, вверх до 10» — как правило считает."""
        if self.is_fixed:
            return f'{money(self.fixed_price)} тг'
        label = self.get_source_display()
        if self.markup:
            label += f' {"+" if self.markup > 0 else "−"} {money(abs(self.markup))} %'
        if self.increase:
            label += f' {"+" if self.increase > 0 else "−"} {money(abs(self.increase))} тг'
        if self.rounding:
            label += f', вверх до {money(self.rounding)}'
        return label

    def scope_label(self, categories=None, brands=None, products=None) -> str:
        """Какие товары правило берёт — одной строкой, для таблицы и предпросмотра.

        Связи — через .all(), чтобы работать с предзагрузкой списка;
        categories/brands/products — для несохранённого правила из формы.
        """
        parts = []
        products = [p.number or p.display_name for p in (self.products.all() if products is None else products)]
        if products:
            parts.append(_listed('товары', products))
        categories = [c.name for c in (self.categories.all() if categories is None else categories)]
        brands = [b.name for b in (self.brands.all() if brands is None else brands)]
        if categories:
            parts.append(_listed('категории', categories))
        if brands:
            parts.append(_listed('бренды', brands))
        if self.only_sets:
            parts.append('только наборы')
        if not self.is_fixed and (self.price_from is not None or self.price_to is not None):
            if self.price_from is not None and self.price_to is not None:
                parts.append(f'{self.get_source_display().lower()} {money(self.price_from)}–{money(self.price_to)} тг')
            elif self.price_from is not None:
                parts.append(f'{self.get_source_display().lower()} от {money(self.price_from)} тг')
            else:
                parts.append(f'{self.get_source_display().lower()} до {money(self.price_to)} тг')
        return '; '.join(parts) if parts else 'все товары'

    def compute(self, source_value):
        """Расчётная цена из цены-источника; None — считать не из чего.

        Пустой или нулевой источник — «цены нет», как и у наценок поставщика:
        правило никогда не превращает отсутствие цены в надбавку.
        """
        if self.is_fixed:
            value = self.fixed_price
        else:
            if not source_value:
                return None
            value = Decimal(source_value) * (1 + self.markup / 100) + self.increase
        if value is None:
            return None
        if self.rounding:
            value = (value / self.rounding).to_integral_value(rounding=ROUND_CEILING) * self.rounding
        return value.quantize(Decimal('0.01'))


class ProductPrice(models.Model):
    """Расчётная цена товара одного типа — результат одной наценки.

    Пишет только services.calculate_product_prices; строка исчезает, когда
    товару перестало подходить любое правило этого типа. source_value и rule —
    след: из чего и каким правилом цена получена в момент расчёта.
    """

    product = models.ForeignKey('product.Product', on_delete=models.CASCADE, related_name='prices',
                                verbose_name='Товар')
    price_type = models.ForeignKey(ProductPriceType, on_delete=models.CASCADE, related_name='prices',
                                   verbose_name='Тип цены')
    value = models.DecimalField('Цена', max_digits=20, decimal_places=2)
    source_value = models.DecimalField('Цена-источник', max_digits=20, decimal_places=2, null=True, blank=True)
    rule = models.ForeignKey(ProductPriceRule, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='prices', verbose_name='Наценка')
    calculated_at = models.DateTimeField('Рассчитана', default=timezone.now)

    class Meta:
        verbose_name = 'Расчётная цена товара'
        verbose_name_plural = 'Расчётные цены товаров'
        constraints = [
            models.UniqueConstraint(fields=['product', 'price_type'], name='product_price_product_type_uniq'),
        ]

    def __str__(self) -> str:
        return f'{self.product_id} · {self.price_type_id}: {self.value}'
