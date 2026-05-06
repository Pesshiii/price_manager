from django.db import models

from core.models import TimeStampedModel

from .productmodels import Product


class PriceType(models.Model):
    name = models.CharField(
        verbose_name='Название цены',
        primary_key=True,
        max_length=255
    )



class Price(TimeStampedModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name='Продукт',
        related_name='prices'
    )
    parent = models.ForeignKey(
        'self',
        verbose_name='Источник цены',
        null=True,
        on_delete=models.SET_NULL, 
        related_name='children')
    ptype = models.ForeignKey(
        PriceType,
        on_delete=models.CASCADE,
        verbose_name='Тип цены',
        related_name='prices'
    )
    value = models.DecimalField(
      verbose_name='Значение',
      decimal_places=2,
      max_digits=20,
      null=True)
    mute = models.BooleanField(
        verbose_name='Устаревшая',
        default=False
    )
    class Meta:
        verbose_name='Цена'