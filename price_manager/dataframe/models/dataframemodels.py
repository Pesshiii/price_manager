from django.db import models

from core.models import SlugModel, TimeStampedModel

from .filemodels import FileModel


class Dataframe(TimeStampedModel, SlugModel):
    file = models.ForeignKey(
        FileModel,
        on_delete=models.PROTECT,
        related_name='dataframes',
        verbose_name='Файл',
    )
    sheet_name = models.CharField(
        verbose_name='Название листа',
        null=True,
        )
    def __str__(self):
        return self.name