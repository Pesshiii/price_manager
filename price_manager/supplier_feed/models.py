from django.db import models


# ── SupplierFeed lifecycle statuses ─────────────────────────────────────────

STATUS_DRAFT = 'draft'
STATUS_PROCESSING = 'processing'
STATUS_MATCHED = 'matched'
STATUS_PARTIAL = 'partial'
STATUS_DONE = 'done'
STATUS_ERROR = 'error'

STATUS_CHOICES = [
    (STATUS_DRAFT, 'Черновик'),
    (STATUS_PROCESSING, 'Обрабатывается'),
    (STATUS_MATCHED, 'Сматчено'),
    (STATUS_PARTIAL, 'Частично'),
    (STATUS_DONE, 'Завершено'),
    (STATUS_ERROR, 'Ошибка'),
]


class FeedMapping(models.Model):
    supplier = models.ForeignKey(
        'supplier.Supplier',
        on_delete=models.CASCADE,
        verbose_name='Поставщик',
        related_name='feed_mappings',
    )
    dataframe = models.ForeignKey(
        'dataframe.Dataframe',
        on_delete=models.PROTECT,
        verbose_name='Pipeline',
        related_name='feed_mappings',
    )
    name = models.CharField('Название', max_length=255)
    supplier_sku_column = models.CharField('Колонка артикула поставщика', max_length=128)
    identity_columns = models.JSONField('Identity-колонки', default=list, blank=True)
    variable_columns = models.JSONField('Переменные колонки', default=list, blank=True)
    auto_match_threshold = models.FloatField('Порог авто-матчинга', default=0.92)
    product_name_column = models.CharField('Колонка названия товара', max_length=128, blank=True)
    product_sku_column = models.CharField('Колонка артикула товара', max_length=128, blank=True)

    class Meta:
        verbose_name = 'Конфигурация выгрузки'
        verbose_name_plural = 'Конфигурации выгрузок'
        ordering = ['supplier', 'name']

    def __str__(self):
        return f'{self.supplier} — {self.name}'


class SupplierFeed(models.Model):
    """Сессия выгрузки прайса поставщика."""

    supplier = models.ForeignKey(
        'supplier.Supplier',
        on_delete=models.PROTECT,
        verbose_name='Поставщик',
        related_name='supplier_feeds',
    )
    feed_mapping = models.ForeignKey(
        FeedMapping,
        on_delete=models.PROTECT,
        verbose_name='Конфигурация',
        related_name='supplier_feeds',
    )
    status = models.CharField(
        'Статус',
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    session_ids = models.JSONField('ID сессий файлов', default=list)
    error = models.TextField('Ошибка', blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Сессия выгрузки'
        verbose_name_plural = 'Сессии выгрузок'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.supplier} / {self.feed_mapping.name} [{self.status}]'


class SupplierFeedEntry(models.Model):
    """Строка из загруженного файла поставщика."""

    feed = models.ForeignKey(
        SupplierFeed,
        on_delete=models.CASCADE,
        verbose_name='Сессия',
        related_name='entries',
    )
    product = models.ForeignKey(
        'product.Product',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name='Товар',
    )
    supplier_sku = models.CharField('Артикул поставщика', max_length=128, db_index=True)
    data = models.JSONField('Данные строки', default=dict)
    match_candidates = models.JSONField('Кандидаты на матчинг', default=list)
    best_score = models.FloatField('Лучший скор матчинга', null=True, blank=True)
    skipped = models.BooleanField('Пропущено', default=False)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Строка выгрузки'
        verbose_name_plural = 'Строки выгрузок'
        indexes = [
            models.Index(fields=['feed', 'product']),
            models.Index(fields=['feed', 'supplier_sku']),
        ]

    def __str__(self):
        return f'{self.feed_id} / {self.supplier_sku}'


class SupplierLink(models.Model):
    """Постоянная связь артикула поставщика с товаром в каталоге."""

    supplier = models.ForeignKey(
        'supplier.Supplier',
        on_delete=models.CASCADE,
        verbose_name='Поставщик',
    )
    supplier_sku = models.CharField('Артикул поставщика', max_length=128)
    product = models.ForeignKey(
        'product.Product',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name='Товар',
    )

    class Meta:
        verbose_name = 'Связь поставщик — товар'
        verbose_name_plural = 'Связи поставщик — товар'
        unique_together = [('supplier', 'supplier_sku')]

    def __str__(self):
        return f'{self.supplier} {self.supplier_sku} → {self.product_id}'
