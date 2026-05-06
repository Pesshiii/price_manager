from django.db import models

from .dataframemodels import Dataframe
from .contenttypemodels import ContentType


class Link(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=['dataframe', 'contenttype'], name='contentitem')]
    dataframe = models.ForeignKey(Dataframe,
                              on_delete=models.CASCADE,
                              related_name='links',
                              blank=True)
    initial = models.CharField(null=True)
    contenttype = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name='Контент'
    )
    value = models.CharField(
        null=True
    )
    def __str__(self):
        return f'{self.contenttype}<--->{self.value}({self.initial})'