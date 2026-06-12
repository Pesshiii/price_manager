from django.db import models


class PriceType(models.Model):
    name = models.SlugField('Ключ', max_length=64, unique=True, allow_unicode=True)
    label = models.CharField('Название', max_length=255)

    class Meta:
        verbose_name = 'Тип цены'
        verbose_name_plural = 'Типы цен'
        ordering = ['label']

    def __str__(self):
        return self.label


class PricingRule(models.Model):
    MODE_FIXED = 'fixed'
    MODE_FORMULA = 'formula'
    MODE_CHOICES = [
        (MODE_FIXED, 'Фиксированная'),
        (MODE_FORMULA, 'Формула'),
    ]

    supplier = models.ForeignKey(
        'supplier.Supplier',
        on_delete=models.CASCADE,
        related_name='pricing_rules',
        verbose_name='Поставщик',
    )
    source_price_type = models.ForeignKey(
        PriceType,
        on_delete=models.PROTECT,
        related_name='source_rules',
        verbose_name='Тип цены-источника',
    )
    dest_price_type = models.ForeignKey(
        PriceType,
        on_delete=models.PROTECT,
        related_name='dest_rules',
        verbose_name='Тип цены-назначения',
    )
    mode = models.CharField('Режим', max_length=32, choices=MODE_CHOICES)
    params = models.JSONField('Параметры', default=dict, blank=True)
    priority = models.PositiveIntegerField('Приоритет', default=0)
    category = models.ForeignKey(
        'product.Category',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='pricing_rules',
        verbose_name='Категория',
    )
    price_from = models.DecimalField(
        'Цена от', max_digits=14, decimal_places=4, null=True, blank=True
    )
    price_to = models.DecimalField(
        'Цена до', max_digits=14, decimal_places=4, null=True, blank=True
    )
    date_from = models.DateTimeField('Дата начала', null=True, blank=True)
    date_to = models.DateTimeField('Дата окончания', null=True, blank=True)

    class Meta:
        verbose_name = 'Правило ценообразования'
        verbose_name_plural = 'Правила ценообразования'
        ordering = ['supplier', 'priority']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.mode == 'formula':
            required = {'markup', 'increase'}
            missing = required - set(self.params.keys())
            if missing:
                raise ValidationError({'params': f"Для режима 'formula' требуются ключи: {missing}"})
        elif self.mode == 'fixed':
            if 'value' not in self.params:
                raise ValidationError({'params': "Для режима 'fixed' требуется ключ 'value'"})

    def __str__(self):
        return f'{self.supplier} / {self.source_price_type} → {self.dest_price_type}'


class ProductPrice(models.Model):
    product = models.ForeignKey(
        'product.Product',
        on_delete=models.CASCADE,
        related_name='prices',
        verbose_name='Товар',
    )
    supplier = models.ForeignKey(
        'supplier.Supplier',
        on_delete=models.CASCADE,
        related_name='product_prices',
        verbose_name='Поставщик',
    )
    price_type = models.ForeignKey(
        PriceType,
        on_delete=models.PROTECT,
        related_name='product_prices',
        verbose_name='Тип цены',
    )
    value = models.DecimalField('Значение', max_digits=14, decimal_places=4)
    rule = models.ForeignKey(
        PricingRule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='product_prices',
        verbose_name='Правило',
    )
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Цена товара'
        verbose_name_plural = 'Цены товаров'
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'supplier', 'price_type'],
                name='pricing_productprice_unique',
            )
        ]
        indexes = [
            models.Index(fields=['supplier', 'price_type'], name='pricing_pp_sup_pt_idx'),
        ]

    def __str__(self):
        return f'{self.product} / {self.supplier} / {self.price_type}: {self.value}'


class Stock(models.Model):
    product = models.ForeignKey(
        'product.Product',
        on_delete=models.CASCADE,
        related_name='stocks',
        verbose_name='Товар',
    )
    supplier = models.ForeignKey(
        'supplier.Supplier',
        on_delete=models.CASCADE,
        related_name='stocks',
        verbose_name='Поставщик',
    )
    quantity = models.PositiveIntegerField('Остаток', default=0)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Остаток'
        verbose_name_plural = 'Остатки'
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'supplier'],
                name='pricing_stock_unique',
            )
        ]

    def __str__(self):
        return f'{self.product} / {self.supplier}: {self.quantity}'
