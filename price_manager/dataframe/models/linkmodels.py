from django.db import models

from .dataframemodels import Dataframe

from core.models import SlugModel

class ContentType(SlugModel):
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


class DictItem(models.Model):
    link = models.ForeignKey(Link,
                            on_delete=models.CASCADE,
                            verbose_name='Столбец',
                            related_name='dicts',
                            blank=True,
                            null=True)
    key = models.CharField(verbose_name='Если')
    value = models.CharField(verbose_name='То')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['link', 'key', 'value'], name='linkdict')]