from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class PriceManager(models.Model):
    name = models.CharField(verbose_name='Название', unique=True)
    supplier = models.ForeignKey(
        'supplier_manager.Supplier',
        on_delete=models.CASCADE,
        verbose_name='Поставщик',
        related_name='price_managers',
        null=True,
    )
    has_rrp = models.BooleanField(
        verbose_name='Есть РЦ',
        choices=[(None, 'Без разницы'), (True, 'Да'), (False, 'Нет')],
        null=True,
        blank=True,
    )
    discounts = models.ManyToManyField(
        'supplier_manager.Discount',
        verbose_name='Группа скидок',
        related_name='price_managers',
        blank=True,
    )
    source = models.CharField(
        verbose_name='От какой цены считать',
        choices=[
            ('rrp', 'РРЦ в валюте поставщика'),
            ('supplier_price', 'Цена поставщика в валюте поставщика'),
            ('basic_price', 'Базовая цена'),
            ('prime_cost', 'Себестоимость'),
            ('m_price', 'Цена ИМ'),
            ('wholesale_price', 'Оптовая цена'),
            ('wholesale_price_extra', 'Оптовая цена1'),
        ],
    )
    dest = models.CharField(
        verbose_name='Какую цену считать',
        choices=[
            ('basic_price', 'Базовая цена'),
            ('prime_cost', 'Себестоимость'),
            ('m_price', 'Цена ИМ'),
            ('wholesale_price', 'Оптовая цена'),
            ('wholesale_price_extra', 'Оптовая цена1'),
        ],
    )
    price_from = models.DecimalField(
        verbose_name='Цена от',
        decimal_places=2,
        max_digits=20,
        validators=[MinValueValidator(Decimal('0'))],
        null=True,
        blank=True,
    )
    price_to = models.DecimalField(
        verbose_name='Цена до',
        decimal_places=2,
        max_digits=20,
        validators=[MinValueValidator(Decimal('0'))],
        null=True,
        blank=True,
    )
    markup = models.DecimalField(
        verbose_name='Накрутка',
        decimal_places=2,
        max_digits=5,
        validators=[MinValueValidator(-100), MaxValueValidator(100)],
        default=0,
    )
    increase = models.DecimalField(
        verbose_name='Надбавка',
        decimal_places=2,
        max_digits=20,
        default=0,
    )

    class Meta:
        verbose_name = 'Наценка'
        verbose_name_plural = 'Наценки'

    def __str__(self):
        return self.name
