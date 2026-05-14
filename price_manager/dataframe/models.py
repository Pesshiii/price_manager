from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

from .registry import READERS, TRANSFORMS


def default_instructions():
    return {'reader': {'func': '', 'args': {}}, 'transforms': []}


class Dataframe(models.Model):
    name = models.CharField('Название', max_length=255, unique=True)
    description = models.TextField('Описание', blank=True)
    instructions = models.JSONField('Инструкции', default=default_instructions, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dataframe'
        verbose_name_plural = 'Dataframes'
        ordering = ['-updated_at']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('dataframe:edit', kwargs={'pk': self.pk})

    @property
    def reader_name(self) -> str:
        return (self.instructions or {}).get('reader', {}).get('func', '') or ''

    @property
    def transform_steps(self) -> list[dict]:
        return list((self.instructions or {}).get('transforms', []) or [])

    def clean(self):
        instructions = self.instructions or {}
        reader = instructions.get('reader') or {}
        rname = reader.get('func')
        if not rname:
            raise ValidationError({'instructions': 'Не указана функция чтения.'})
        if rname not in READERS:
            raise ValidationError({'instructions': f"Неизвестная функция чтения: {rname}"})
        for i, step in enumerate(instructions.get('transforms') or []):
            tname = step.get('func')
            if tname not in TRANSFORMS:
                raise ValidationError(
                    {'instructions': f"Шаг {i+1}: неизвестная трансформация '{tname}'"}
                )
