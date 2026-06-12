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


class FeedMarkupSet(models.Model):
    """Набор правил наценки для одной пары (price_column → output_column) в рамках FeedMapping."""

    feed_mapping = models.ForeignKey(
        FeedMapping,
        on_delete=models.CASCADE,
        verbose_name='Конфигурация выгрузки',
        related_name='markup_sets',
    )
    name = models.CharField('Название', max_length=255)
    price_column = models.CharField('Колонка цены-источника', max_length=128)
    output_column = models.CharField('Колонка расчётной цены', max_length=128)

    class Meta:
        verbose_name = 'Набор наценок'
        verbose_name_plural = 'Наборы наценок'
        ordering = ['feed_mapping', 'name']

    def __str__(self):
        return f'{self.feed_mapping} / {self.name}'


class FeedMarkupRule(models.Model):
    """Одно ценовое правило внутри FeedMarkupSet."""

    markup_set = models.ForeignKey(
        FeedMarkupSet,
        on_delete=models.CASCADE,
        verbose_name='Набор наценок',
        related_name='rules',
    )
    order = models.PositiveIntegerField('Приоритет', default=0, db_index=True)
    price_from = models.DecimalField(
        'Цена от', max_digits=14, decimal_places=4, null=True, blank=True
    )
    price_to = models.DecimalField(
        'Цена до', max_digits=14, decimal_places=4, null=True, blank=True
    )
    markup = models.DecimalField('Наценка %', max_digits=10, decimal_places=4, default=0)
    increase = models.DecimalField('Надбавка', max_digits=14, decimal_places=4, default=0)

    class Meta:
        verbose_name = 'Правило наценки'
        verbose_name_plural = 'Правила наценок'
        ordering = ['order']

    def __str__(self):
        lo = float(self.price_from) if self.price_from is not None else '–∞'
        hi = float(self.price_to) if self.price_to is not None else '+∞'
        return f'{self.markup_set} [{lo}–{hi}] +{self.markup}% +{self.increase}'


class FeedColumnMapping(models.Model):
    ROLE_PRICE = 'price'
    ROLE_STOCK = 'stock'
    ROLE_OTHER = 'other'
    ROLE_CHOICES = [
        (ROLE_PRICE, 'Цена'),
        (ROLE_STOCK, 'Остаток'),
        (ROLE_OTHER, 'Другое'),
    ]

    feed_mapping = models.ForeignKey(
        FeedMapping,
        on_delete=models.CASCADE,
        related_name='column_mappings',
        verbose_name='Конфигурация выгрузки',
    )
    column_name = models.CharField('Колонка', max_length=128)
    role = models.CharField('Роль', max_length=16, choices=ROLE_CHOICES)
    price_type = models.ForeignKey(
        'pricing.PriceType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='column_mappings',
        verbose_name='Тип цены',
    )

    class Meta:
        verbose_name = 'Маппинг колонки'
        verbose_name_plural = 'Маппинги колонок'
        constraints = [
            models.UniqueConstraint(
                fields=['feed_mapping', 'column_name'],
                name='supplier_feed_column_mapping_unique',
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(role='price') | models.Q(price_type__isnull=False)
                ),
                name='supplier_feed_column_mapping_price_requires_type',
            ),
        ]

    def __str__(self):
        return f'{self.feed_mapping} / {self.column_name} [{self.role}]'


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
