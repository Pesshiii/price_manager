from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from django.db.models import Value
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


class Brand(models.Model):
    """Бренд из PIM. Ключ — brandId, как его отдаёт PIM.

    Словаря вариаций написания намеренно нет: brandId из PIM — это ссылка на
    сущность, а не свободный текст, поэтому нормализовать нечего.
    supplier_manager.ManufacturerDict решал ровно эту задачу для названий от
    поставщиков и не использовался ни разу — 0 строк на проде.
    """

    pim_id = models.CharField('Id бренда в PIM', max_length=64, unique=True)
    name = models.CharField('Название', max_length=255)

    class Meta:
        verbose_name = 'Бренд'
        verbose_name_plural = 'Бренды'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    # Id of this Product's PriceManagerProduct in PIM — the through record whose
    # platformID is our pk and whose productId points at the PIM Product. NULL
    # until reindex_pim_ids pushes it.
    pim_id = models.CharField(
        'Id связи в PIM (PriceManagerProduct)', max_length=64, null=True, blank=True, unique=True,
    )
    # The match key: MainProduct.sku. Local, never overwritten from PIM.
    number = models.CharField('Артикул', max_length=128, null=True, blank=True, unique=True)
    # Not unique: several Products can sit on one PIM Product, and PIM does not
    # keep Product.name unique either.
    name = models.CharField('Название', max_length=512, null=True, blank=True)
    categories = models.ManyToManyField(
        Category, related_name='products', blank=True, verbose_name='Категории',
    )
    brand = models.ForeignKey(
        Brand,
        related_name='products',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Бренд',
    )
    raw_data = models.JSONField('Сырые данные PIM', default=dict, blank=True)
    search_vector = SearchVectorField('Вектор поиска', null=True, editable=False)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['-updated_at']
        indexes = [
            GinIndex(fields=['search_vector'], name='product_search_vector_gin'),
        ]

    def __str__(self) -> str:
        return f'{self.number} — {self.name}'

    @property
    def display_name(self) -> str:
        """Название для показа.

        `name` приходит из PIM и пуст у каждой строки, которую засеяла миграция
        0005 и которую ещё не синхронизировали (154 969 строк на проде на
        2026-09-03). Пустая ячейка в таблице — это не «нет названия», а «ещё не
        сходили в PIM», поэтому откатываемся на название любого из связанных
        MainProduct: его заполняет прайс поставщика, и оно есть всегда.
        """
        if self.name:
            return self.name
        main_product = self.main_products.first()
        return main_product.name if main_product else (self.number or self.pim_id)

    def _build_searchvector(self) -> SearchVector:
        """Вектор поиска строится ТОЛЬКО из локальных данных.

        Никаких обращений к PIM: всё, что нужно, уже лежит в raw_data, который
        пишет sync_product_from_pim. Это главное отличие от
        MainProduct._build_searchvector(), который ходил в сеть прямо из метода
        модели и делал это на каждое сохранение.

        Разделитель — пробел, а не ''. В MainProduct стояло ''.join(...), из-за
        чего названия категорий склеивались в один токен («ДушКабины» вместо
        «Душ» + «Кабины») и по отдельному слову категория не находилась.
        """
        data = self.raw_data or {}
        categories = ' '.join((data.get('categoriesNames') or {}).values())
        tags = ' '.join(data.get('tag') or [])
        return (
            SearchVector(Value(categories), weight='A', config='russian') +
            SearchVector(Value(tags), weight='A', config='russian') +
            SearchVector(Value(data.get('name') or ''), weight='A', config='russian') +
            SearchVector(Value(self.number or ''), weight='B', config='russian') +
            SearchVector(Value(data.get('brandName') or ''), weight='B', config='russian') +
            SearchVector(Value(data.get('description') or ''), weight='C', config='russian') +
            SearchVector(Value(data.get('longDescription') or ''), weight='C', config='russian')
        )

    def rebuild_search_vector(self) -> None:
        """Пересобирает search_vector через update() — без join-полей в SET."""
        Product.objects.filter(pk=self.pk).update(search_vector=self._build_searchvector())
