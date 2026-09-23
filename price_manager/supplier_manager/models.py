from datetime import timedelta

from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

PRIORITY_FIELDS = ('price_priority', 'stock_priority')


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
        verbose_name='Приоритет по цене',
        help_text='Меньше — выше приоритет. Пусто — поставщик не проранжирован.',
        null=True,
        blank=True,
    )
    stock_priority = models.PositiveIntegerField(
        verbose_name='Приоритет по остаткам',
        help_text='Меньше — выше приоритет. Пусто — поставщик не проранжирован.',
        null=True,
        blank=True,
    )
    class Meta:
        verbose_name = 'Поставщик'
        ordering = ['name']
        # DEFERRED: перенумерация идёт одним UPDATE, и посреди него номера
        # на мгновение совпадают. Проверка — при коммите.
        constraints = [
            models.UniqueConstraint(
                fields=[field],
                name=f'supplier_unique_{field}',
                deferrable=models.Deferrable.DEFERRED,
            )
            for field in PRIORITY_FIELDS
        ]
    def __str__(self):
        return self.name

    def validate_constraints(self, exclude=None):
        # Занятый приоритет — не ошибка формы: save() ставит поставщика на
        # этот номер и перенумеровывает остальных (place).
        super().validate_constraints(exclude={*(exclude or ()), *PRIORITY_FIELDS})

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        with transaction.atomic():
            old = {}
            if self.pk is not None:
                old = Supplier.objects.filter(pk=self.pk).values(*PRIORITY_FIELDS).first() or {}
            self.shifted = {
                field: self.place(field)
                for field in PRIORITY_FIELDS
                if (update_fields is None or field in update_fields)
                and getattr(self, field) != old.get(field)
            }
            super().save(*args, **kwargs)

    def place(self, field):
        """Ставит поставщика на номер `field` в сплошной нумерации 1…N.

        Проранжированные поставщики всегда занимают номера 1…N без пропусков
        и повторов. Номер больше N+1 становится последним, меньше 1 — первым;
        пустой номер убирает поставщика из рейтинга, и остальные смыкаются.
        Возвращает pk поставщиков, чей номер поменялся.
        """
        current = dict(
            Supplier.objects.select_for_update()
            .exclude(pk=self.pk)
            .filter(**{f'{field}__isnull': False})
            .order_by(field, 'name')
            .values_list('pk', field)
        )
        order = list(current)
        value = getattr(self, field)
        if value is not None:
            value = min(max(value, 1), len(order) + 1)
            setattr(self, field, value)
            order.insert(value - 1, None)  # место этого поставщика
        return Supplier._apply_order(field, order, current)

    @staticmethod
    def _apply_order(field, order, current):
        """Пишет номера 1…N по списку pk (None — пропустить) одним UPDATE."""
        changed = {
            pk: n for n, pk in enumerate(order, 1)
            if pk is not None and current[pk] != n
        }
        if changed:
            Supplier.objects.filter(pk__in=changed).update(**{field: models.Case(
                *(models.When(pk=pk, then=n) for pk, n in changed.items()),
                output_field=models.PositiveIntegerField(),
            )})
        return list(changed)

    @classmethod
    def renumber(cls, field):
        """Смыкает нумерацию `field` после удаления поставщика."""
        current = dict(
            cls.objects.select_for_update()
            .filter(**{f'{field}__isnull': False})
            .order_by(field, 'name')
            .values_list('pk', field)
        )
        return cls._apply_order(field, list(current), current)

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
  

@receiver(post_delete, sender=Supplier)
def _close_priority_gaps(sender, instance, **kwargs):
    # Срабатывает и при queryset.delete(): Django шлёт сигнал на каждый объект.
    for field in PRIORITY_FIELDS:
        if getattr(instance, field) is not None:
            Supplier.renumber(field)


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
