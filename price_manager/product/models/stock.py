from django.db import models
from .product import Product
from core.models import TimeStampedModel

class StockType(models.Model):
    name = models.CharField(
        verbose_name='Название цены',
        primary_key=True,
        max_length=255
    )


class Stock(TimeStampedModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name='Продукт',
        related_name='stocks'
    )
    parent = models.ForeignKey(
        'self',
        verbose_name='Источник цены',
        null=True,
        on_delete=models.SET_NULL, 
        related_name='children')
    stype = models.ForeignKey(
        StockType,
        on_delete=models.CASCADE,
        verbose_name='Тип остатка',
        related_name='stocks'
    )
    value = models.PositiveIntegerField(
        verbose_name='Значение',
        null=True)
    mute = models.BooleanField(
        verbose_name='Устаревший',
        default=False
    )
    class Meta:
        verbose_name='Остаток'
