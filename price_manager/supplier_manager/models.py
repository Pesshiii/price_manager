from django.core.validators import MinValueValidator
from django.db import models

TIME_FREQ = {
    'Каждый день': 1,
    'Каждую неделю': 7,
    'Каждые три недели': 21,
}

SUPPLIER_SPECIFIABLE_FIELDS = ['name', 'delivery_days', 'currency', 'price_update_rate', 'stock_update_rate']

SP_TABLE_FIELDS = [
    'article',
    'name',
    'category',
    'manufacturer',
    'stock',
    'supplier_price',
    'rrp',
]
SP_FKS = ['category', 'discounts', 'manufacturer']
SP_PRICES = ['supplier_price', 'rrp']
SP_INTEGERS = ['stock']


class Currency(models.Model):
    name = models.CharField(verbose_name='Название', unique=True)
    value = models.DecimalField(verbose_name='Тенге', max_digits=1000, decimal_places=2)

    class Meta:
        verbose_name = 'Валюта'
        verbose_name_plural = 'Валюты'

    def __str__(self):
        return self.name


class Supplier(models.Model):
    name = models.CharField(verbose_name='Поставщик', unique=True)
    price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены', null=True, blank=True)
    currency = models.ForeignKey(
        Currency,
        verbose_name='Валюта поставщика',
        on_delete=models.PROTECT,
        default=1,
    )
    stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка', null=True, blank=True)
    delivery_days = models.PositiveIntegerField(verbose_name='Срок доставки', default=0)
    price_update_rate = models.CharField(
        verbose_name='Частота обновления цен', choices=[(_, _) for _ in TIME_FREQ.keys()]
    )
    stock_update_rate = models.CharField(
        verbose_name='Частота обновления остатков', choices=[(_, _) for _ in TIME_FREQ.keys()]
    )

    class Meta:
        verbose_name = 'Поставщик'
        verbose_name_plural = 'Поставщики'

    def __str__(self):
        return self.name


class Discount(models.Model):
    name = models.CharField(verbose_name='Название')
    supplier = models.ForeignKey(
        Supplier,
        verbose_name='Поставщик',
        on_delete=models.CASCADE,
        related_name='discounts',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['name', 'supplier'], name='discount_name_supplier_constraint'),
        ]
        verbose_name = 'Скидка'
        verbose_name_plural = 'Скидки'

    def __str__(self):
        return self.name


class SupplierProduct(models.Model):
    main_product = models.ForeignKey(
        'main_price.MainProduct',
        verbose_name='Главный продукт',
        related_name='supplier_product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    supplier = models.ForeignKey(
        Supplier,
        verbose_name='Поставщик',
        related_name='supplier_products',
        on_delete=models.CASCADE,
    )
    article = models.CharField(verbose_name='Артикул поставщика')
    name = models.CharField(verbose_name='Название')
    category = models.ForeignKey(
        'main_price.Category',
        on_delete=models.SET_NULL,
        verbose_name='Категория',
        null=True,
        blank=True,
    )
    discounts = models.ManyToManyField(
        Discount,
        verbose_name='Группа скидок',
        related_name='products',
        blank=True,
    )
    manufacturer = models.ForeignKey(
        'main_price.Manufacturer',
        verbose_name='Производитель',
        related_name='supplier_product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    stock = models.PositiveIntegerField(verbose_name='Остаток', default=0)
    supplier_price = models.DecimalField(verbose_name='Цена поставщика в валюте поставщика', decimal_places=2, max_digits=20, default=0)
    rrp = models.DecimalField(verbose_name='РРЦ в валюте поставщика', decimal_places=2, max_digits=20, default=0)
    updated_at = models.DateTimeField(verbose_name='Последнее обновление', auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['supplier', 'article', 'name'],
                name='sp_uniqe_supplier_article_name',
            )
        ]
        verbose_name = 'Товар поставщика'
        verbose_name_plural = 'Товары поставщиков'

    def __str__(self):
        return f'{self.name} ({self.supplier})'

