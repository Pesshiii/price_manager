from django.db import models
from django.core.serializers import json

from core.models import TimeStampedModel
from mptt.models import MPTTModel, TreeForeignKey


# Create your models here.


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


class Category(MPTTModel):
    parent = TreeForeignKey(
        'self',
        on_delete=models.PROTECT,
        verbose_name='Подкатегория для',
        related_name='children',
        null=True,
        blank=True,
    )
    name = models.CharField(
        verbose_name='Название',
        null=False,
    )
    contenttypes=models.ManyToManyField(
        ContentType,
        related_name='categories',
        verbose_name='Тип конента',
    )


class Product(TimeStampedModel):
    slug = models.SlugField(
        verbose_name="Строка идентификатор для url", 
        unique=True
    )
    description = models.CharField(
        verbose_name="HTML для продукта"
    )
    category = models.ForeignKey(
        Category,
        related_name='products',
        verbose_name='Категория',
        null=True,
        on_delete=models.SET_NULL,
    )

class Property(models.Model):
    content = models.JSONField(
        verbose_name='Контент',
        serialize=json.DjangoJSONEncoder
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='properties',
        verbose_name='Продукт',
    )