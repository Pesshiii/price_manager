from django.db import models
from django.core.serializers import json

from core.models import TimeStampedModel, SlugModel

from .productmodels import Product



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