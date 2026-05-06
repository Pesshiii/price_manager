from django.db import models

from core.models import TimeStampedModel, SlugModel

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
