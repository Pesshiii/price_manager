from __future__ import annotations

from django.db import models
from django.utils.text import slugify
from mptt.models import MPTTModel, TreeForeignKey


class Category(MPTTModel):
    parent = TreeForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='children',
        null=True,
        blank=True,
        verbose_name='Родительская категория',
    )
    name = models.CharField('Название', max_length=255)
    slug = models.SlugField('Слаг', max_length=255, unique=True)
    pim_id = models.CharField(
        'Id категории в PIM', max_length=64, null=True, blank=True, unique=True,
    )

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        constraints = [
            models.UniqueConstraint(fields=['parent', 'name'], name='product_category_parent_name_uniq'),
        ]

    class MPTTMeta:
        order_insertion_by = ['name']

    def __str__(self) -> str:
        return f'{self.parent}>{self.name}' if self.parent_id else self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=True) or 'category'
            slug = base
            i = 2
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Product(models.Model):
    pim_id = models.CharField('Id товара в PIM', max_length=64, unique=True)
    number = models.CharField('Номер PIM (артикул)', max_length=128, null=True, blank=True, unique=True)
    name = models.CharField('Название', max_length=512, unique=True, null=True, blank=True)
    categories = models.ManyToManyField(
        Category, related_name='products', blank=True, verbose_name='Категории',
    )
    raw_data = models.JSONField('Сырые данные PIM', default=dict, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['-updated_at']

    def __str__(self) -> str:
        return f'{self.number} — {self.name}'
