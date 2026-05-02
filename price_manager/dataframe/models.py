from django.db import models
from django.core.validators import FileExtensionValidator
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from core.models import SlugModel, TimeStampedModel

from product.models import ContentType

# Create your models here.


class FileModel(models.Model):
    file = models.FileField(
        verbose_name='Файл',
        validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm', 'csv'])],
        null=False,
        upload_to='dataframe/'
    )

@receiver(pre_delete, sender=FileModel)
def document_pre_delete(sender, instance, **kwargs):
    """Clean up file before model deletion"""
    instance.file.delete(save=False)

class Dataframe(TimeStampedModel, SlugModel):
  sheet_name = models.CharField(verbose_name='Название листа')
  create_new = models.BooleanField(verbose_name='Создавать если нет',
                                   default=False)
  index_row = models.IntegerField(verbose_name='Ряд для индексации',
                                   null=True, blank=True)
  def __str__(self):
    return self.name


class DictItem(models.Model):
  link = models.ForeignKey('Link',
                           on_delete=models.CASCADE,
                           verbose_name='Столбец',
                           related_name='dicts',
                           blank=True,
                           null=True)
  key = models.CharField(verbose_name='Если')
  value = models.CharField(verbose_name='То')
  class Meta:
    constraints = [models.UniqueConstraint(fields=['link', 'key', 'value'], name='linkdict')]


class Link(models.Model):
  class Meta:
    constraints = [models.UniqueConstraint(fields=['dataframe', 'content'], name='contentitem')]
  dataframe = models.ForeignKey(Dataframe,
                              on_delete=models.CASCADE,
                              related_name='links')
  initial = models.CharField(null=True)
  content = models.ForeignKey(
    ContentType,
    on_delete=models.CASCADE,
    verbose_name='Контент'
  )
  value = models.CharField(null=False)
  def __str__(self):
    return f'{self.content}<--->{self.value}({self.initial})'