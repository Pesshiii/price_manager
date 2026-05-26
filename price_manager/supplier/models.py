from django.db import models


class Supplier(models.Model):
    name = models.CharField(
        verbose_name='Поставщик',
        max_length=255,
        unique=True,
    )

    class Meta:
        verbose_name = 'Поставщик'
        verbose_name_plural = 'Поставщики'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name
