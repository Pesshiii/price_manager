from django.db import models
from django.core.serializers import json

from core.models import TimeStampedModel, SlugModel

from .product import Product


class ContentType(models.Model):
    name=models.CharField(
        verbose_name="Название поля"
    )
    measure=models.CharField(
        verbose_name="Еденица измерения"
    )
    contenttype=models.CharField(
        verbose_name="Тип поля",
        choices=[
            ('str','Текст'),
            ('int','Целые числа'),
            ('float', 'числа с плавающей точкой'),
            ('Decimal', 'Десятичные числа'),
        ]
    )



class Manufacturer(TimeStampedModel):
  name = models.CharField(verbose_name='Производитель',
                        unique=True)
  class Meta:
    verbose_name = 'Производитель'
  def __str__(self):
    return self.name
  

class Content(models.Model):
    content = models.JSONField(
        verbose_name='Контент',
        serialize=json.DjangoJSONEncoder
    )
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='content',
        verbose_name='Продукт',
    )