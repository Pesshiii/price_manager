from datetime import timedelta

from django.db import models
from django.utils import timezone

PRIORITY_FIELDS = ('price_priority', 'stock_priority')
PRIORITY_HELP = ('Меньше — выше. Один уровень у нескольких поставщиков — '
                 'цены — у того, чья себестоимость меньше, остаток — максимальный. '
                 'Пусто — общий нижний уровень.')


def format_interval(days):
    """«2 нед.» для кратного неделе интервала, иначе «10 дн.»; пусто — None."""
    if not days:
        return None
    if days % 7 == 0:
        return f'{days // 7} нед.'
    return f'{days} дн.'

# Основные классы для продуктов(главных/поставщика)
  
class Currency(models.Model):
    name = models.CharField(verbose_name='Название',
                            unique=True,
                            null=False)
    value = models.DecimalField(verbose_name='Тенге',
                                max_digits=1000,
                                null=False,
                                decimal_places=2)
    def __str__(self):
        return self.name


OWN_STOCK_NAME = 'Свой склад'


def _get_default_currnecy():
    obj, created = Currency.objects.get_or_create(name="KZT", value=1)
    return obj.pk


class Supplier(models.Model):
    """
    Модель Supplier представляет поставщика товаров.
    Атрибуты:
        name (CharField): Название поставщика (уникальное).
        price_updated_at (DateTimeField): Дата и время последнего обновления цены.
        stock_updated_at (DateTimeField): Дата и время последнего обновления остатка.
        delivery_days (PositiveIntegerField): Срок доставки в днях.
    Методы:
        __str__: Возвращает название поставщика.
    Meta:
        verbose_name: Человекочитаемое имя модели ("Поставщик").
    """
    pim_id = models.CharField(verbose_name='Id для системы Pim',
                                  null=True,
                                  blank=True,
                                  unique=True)
    name = models.CharField(verbose_name='Поставщик',
                            unique=True)
    sku_type = models.CharField(verbose_name='Префикс/Суффикс',
                                choices=[
                                    (None, 'Отсутсвует'),
                                    ('prefix', 'Префикс'),
                                    ('suffix', 'Суффикс')
                                    ],
                                null=True,
                                blank=True)
    sku_value = models.CharField(verbose_name='Значение Префикса/Суффикса',
                                null=True,
                                blank=True)
    currency = models.ForeignKey(Currency,
                                verbose_name='Валюта поставщика',
                                    on_delete=models.PROTECT,
                                    default=_get_default_currnecy,
                                    blank=False)
    price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены', 
                                            null=True,
                                            blank=True)
    stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка', 
                                            null=True,
                                            blank=True)
    delivery_days_available = models.PositiveIntegerField(
        verbose_name='Срок поставки (Рабочие дни) при наличии',
        null=True,
        blank=False,
    )
    delivery_days_navailable = models.PositiveIntegerField(
        verbose_name='Срок поставки (Рабочие дни) при отсутствии',
        null=True,
        blank=False,
    )
    price_update_days = models.PositiveIntegerField(
        verbose_name='Интервал обновления цен',
        help_text='В днях. Пусто — не отслеживать.',
        null=True,
        blank=True,
    )
    stock_update_days = models.PositiveIntegerField(
        verbose_name='Интервал обновления остатков',
        help_text='В днях. Пусто — не отслеживать.',
        null=True,
        blank=True,
    )
    msg_available = models.CharField(verbose_name="Сообщение при наличии",
                                    default="Есть в наличии")
    msg_navailable = models.CharField(verbose_name="Сообщение при отсутствии",
                                        default="Нет в наличии")
    price_priority = models.PositiveIntegerField(
        verbose_name='Уровень по цене',
        help_text=PRIORITY_HELP,
        null=True,
        blank=True,
    )
    stock_priority = models.PositiveIntegerField(
        verbose_name='Уровень по остаткам',
        help_text=PRIORITY_HELP,
        null=True,
        blank=True,
    )
    # «Свой склад»: возвраты, бонусы, остатки на складе — всё, что не из прайса
    # настоящего поставщика. Ведёт себя как любой поставщик (загрузка,
    # копирование в ГП, менеджеры цен, уровни); особенный он в одном — ручные
    # строки ГП по умолчанию заводятся на него, и туда же уходят бывшие строки
    # наборов. Поэтому он один, не удаляется и не переименовывается. Ничего
    # больше этот флаг не значит: остаток строки без строки прайса не трогает
    # update_stocks у любого поставщика.
    is_own_stock = models.BooleanField(verbose_name='Свой склад',
                                       default=False,
                                       editable=False)
    class Meta:
        verbose_name = 'Поставщик'
        constraints = [
            models.UniqueConstraint(fields=['is_own_stock'],
                                    condition=models.Q(is_own_stock=True),
                                    name='supplier_single_own_stock'),
        ]
        ordering = ['name']
    def __str__(self):
        return self.name

    @classmethod
    def own_stock(cls) -> 'Supplier':
        """«Свой склад» — создаётся, если его ещё нет.

        Ищется только по флагу: поставщик, который просто называется так же,
        служебным не становится — новому тогда достаётся имя с номером.
        """
        supplier = cls.objects.filter(is_own_stock=True).first()
        if supplier is not None:
            return supplier
        taken = set(cls.objects.filter(name__startswith=OWN_STOCK_NAME).values_list('name', flat=True))
        name, n = OWN_STOCK_NAME, 2
        while name in taken:
            name = f'{OWN_STOCK_NAME} {n}'
            n += 1
        supplier, _ = cls.objects.get_or_create(is_own_stock=True, defaults={'name': name})
        return supplier

    def update_status(self, kind, now=None):
        """Статус обновления цен (`kind='price'`) или остатков (`'stock'`).

        'untracked' — интервал не задан; 'never' — ни разу не обновлялось;
        'overdue' — с последнего обновления прошло не меньше интервала;
        'ok' — в срок.
        """
        days = getattr(self, f'{kind}_update_days')
        updated_at = getattr(self, f'{kind}_updated_at')
        if not days:
            return 'untracked'
        if updated_at is None:
            return 'never'
        if (now or timezone.now()) - updated_at >= timedelta(days=days):
            return 'overdue'
        return 'ok'

    def get_delivery_days_for_stock(self, stock):
        """Срок поставки по остатку.

        `stock is None` — «остаток ни разу не синхронизировался», а не ноль, и
        это третье состояние, а не синоним отсутствия товара. Срок для него
        всё равно нужно показать, поэтому берётся пессимистичная оценка (как
        при нулевом остатке) — но ветка отдельная и явная, чтобы «не знаем» не
        схлопнулось с «нет» при следующей правке.
        """
        if stock is None:
            return self.delivery_days_navailable
        if stock > 0:
            return self.delivery_days_available
        return self.delivery_days_navailable
  

class Discount(models.Model):
    """
    Модель Discount представляет скидку, связанную с определённым поставщиком.
    Поля:
    - name: Название скидки.
    - supplier: Ссылка на поставщика, к которому относится скидка.
    Ограничения:
    - Уникальность сочетания названия скидки и поставщика.
    """
    
    name = models.CharField(verbose_name='Название',
                            null=False)
    supplier = models.ForeignKey(Supplier,
                                verbose_name='Поставщик',
                                null=False,
                                on_delete=models.CASCADE,
                                related_name='discounts')
    def __str__(self):
        return self.name
    class Meta:
        constraints = [models.UniqueConstraint(fields=['name', 'supplier'], name='discount_name_supplier_constraint')]
