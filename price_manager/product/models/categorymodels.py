from mptt.models import MPTTModel, TreeForeignKey
from django.db import models


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
        'dataframe.ContentType',
        related_name='categories',
        verbose_name='Тип конента',
    )
