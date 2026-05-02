from django.db import models
from core.models import TimeStampedModel, SlugModel




class Product(TimeStampedModel, SlugModel):
    description = models.CharField(
        verbose_name="HTML для продукта"
    )
    category = models.ForeignKey(
        'Category',
        related_name='products',
        verbose_name='Категория',
        null=True,
        on_delete=models.SET_NULL,
    )