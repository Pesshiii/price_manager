from django.db import models


class ProductSnapshot(models.Model):
    product = models.ForeignKey(
        'product.Product',
        on_delete=models.CASCADE,
        verbose_name='Товар',
        related_name='snapshots',
    )
    supplier = models.ForeignKey(
        'supplier.Supplier',
        on_delete=models.CASCADE,
        verbose_name='Поставщик',
        related_name='snapshots',
    )
    source_feed = models.ForeignKey(
        'supplier_feed.SupplierFeed',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Источник выгрузки',
        related_name='snapshots',
    )
    data = models.JSONField(verbose_name='Данные снимка')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлено')

    class Meta:
        verbose_name = 'Снимок товара'
        verbose_name_plural = 'Снимки товаров'
        unique_together = [('product', 'supplier')]
        ordering = ['product', 'supplier']

    def __str__(self):
        return f'{self.product} / {self.supplier}'


class SnapshotField(models.Model):
    VALUE_TYPE_CHOICES = [
        ('number', 'Число'),
        ('string', 'Строка'),
        ('boolean', 'Булево'),
    ]

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=255, verbose_name='Название')
    value_type = models.CharField(
        max_length=16,
        choices=VALUE_TYPE_CHOICES,
        verbose_name='Тип значения',
    )
    description = models.TextField(blank=True, null=True, verbose_name='Описание')

    class Meta:
        verbose_name = 'Поле снимка'
        verbose_name_plural = 'Поля снимков'
        ordering = ['slug']

    def __str__(self):
        return f'{self.name} ({self.slug})'


class TransformRule(models.Model):
    feed_mapping = models.ForeignKey(
        'supplier_feed.FeedMapping',
        on_delete=models.CASCADE,
        verbose_name='Конфигурация выгрузки',
        related_name='transform_rules',
    )
    target_field = models.ForeignKey(
        SnapshotField,
        on_delete=models.PROTECT,
        verbose_name='Целевое поле',
        related_name='transform_rules',
    )
    priority = models.IntegerField(verbose_name='Приоритет')
    condition = models.JSONField(null=True, blank=True, verbose_name='Условие')
    formula = models.JSONField(verbose_name='Формула')

    class Meta:
        verbose_name = 'Правило трансформации'
        verbose_name_plural = 'Правила трансформации'
        ordering = ['feed_mapping', 'priority']

    def __str__(self):
        return f'{self.feed_mapping} / {self.target_field} (prio={self.priority})'
