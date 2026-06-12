from django.db import models


class PriceType(models.Model):
    name = models.SlugField('Ключ', max_length=64, unique=True, allow_unicode=True)
    label = models.CharField('Название', max_length=255)

    class Meta:
        verbose_name = 'Тип цены'
        verbose_name_plural = 'Типы цен'

    def __str__(self):
        return self.label
