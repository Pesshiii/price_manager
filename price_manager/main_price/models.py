from django.contrib.postgres.search import SearchVectorField, SearchVector
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Value


class Category(models.Model):
    parent = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        verbose_name='Подкатегория для',
        null=True,
        blank=True,
    )
    name = models.CharField(verbose_name='Название', null=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['parent', 'name'], name='parent_child_constraint'),
        ]
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'

    def __str__(self):
        if self.parent:
            return f'{self.parent}>{self.name}'
        return self.name


class Manufacturer(models.Model):
    name = models.CharField(verbose_name='Производитель', unique=True)

    class Meta:
        verbose_name = 'Производитель'
        verbose_name_plural = 'Производители'

    def __str__(self):
        return self.name


class ManufacturerDict(models.Model):
    manufacturer = models.ForeignKey(
        Manufacturer,
        verbose_name='Производитель',
        related_name='md_manufacturer_ptr',
        on_delete=models.CASCADE,
    )
    name = models.CharField(verbose_name='Вариация', unique=True, null=False)

    class Meta:
        verbose_name = 'Словарь Производителя'
        verbose_name_plural = 'Словари Производителей'

    def __str__(self):
        return f'{self.name}({self.manufacturer.name})'


MP_TABLE_FIELDS = ['article', 'supplier', 'name', 'manufacturer', 'prime_cost', 'stock']
MP_CHARS = ['sku', 'article', 'name']
MP_FKS = ['supplier', 'category', 'discount', 'manufacturer', 'price_manager']
MP_DECIMALS = ['weight', 'length', 'width', 'depth']
MP_INTEGERS = ['stock']
MP_PRICES = ['prime_cost', 'wholesale_price', 'basic_price', 'm_price', 'wholesale_price_extra']
MP_MANAGMENT = ['price_updated_at', 'stock_updated_at', 'search_vector']


class MainProduct(models.Model):
    sku = models.CharField(verbose_name='Артикул товара', null=True, blank=True)
    supplier = models.ForeignKey(
        'supplier_manager.Supplier',
        verbose_name='Поставщик',
        related_name='mp_supplier_ptr',
        on_delete=models.PROTECT,
    )
    article = models.CharField(verbose_name='Артикул поставщика')
    name = models.CharField(verbose_name='Название')
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        verbose_name='Категория',
        null=True,
        blank=True,
    )
    manufacturer = models.ForeignKey(
        Manufacturer,
        verbose_name='Производитель',
        related_name='mp_manufacturer_ptr',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    stock = models.PositiveIntegerField(verbose_name='Остаток', null=True)
    weight = models.DecimalField(verbose_name='Вес', decimal_places=1, max_digits=8, default=0)
    prime_cost = models.DecimalField(verbose_name='Себестоимость', decimal_places=2, max_digits=20, default=0)
    wholesale_price = models.DecimalField(verbose_name='Оптовая цена', decimal_places=2, max_digits=20, default=0)
    basic_price = models.DecimalField(verbose_name='Базовая цена', decimal_places=2, max_digits=20, default=0)
    m_price = models.DecimalField(verbose_name='Цена ИМ', decimal_places=2, max_digits=20, default=0)
    wholesale_price_extra = models.DecimalField(
        verbose_name='Оптовая цена доп.', decimal_places=2, max_digits=20, default=0
    )
    price_managers = models.ManyToManyField(
        'price_manager.PriceManager',
        verbose_name='Наценка',
        related_name='main_products',
        blank=True,
    )
    length = models.DecimalField(verbose_name='Длина', max_digits=10, decimal_places=2, default=0)
    width = models.DecimalField(verbose_name='Ширина', max_digits=10, decimal_places=2, default=0)
    depth = models.DecimalField(verbose_name='Глубина', max_digits=10, decimal_places=2, default=0)
    price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены', auto_now_add=True)
    stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка', auto_now_add=True)
    search_vector = SearchVectorField(null=True, editable=False, unique=False, verbose_name='Вектор поиска')

    class Meta:
        indexes = [GinIndex(fields=['search_vector'])]
        verbose_name = 'Главный товар'
        verbose_name_plural = 'Главный прайс'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        MainProduct.objects.filter(pk=self.pk).update(search_vector=SearchVector('name', config='russian'))

    def __str__(self):
        return self.sku if self.sku else 'Не указан'

    def _build_search_text(self) -> str:
        parts = [
            self.name or '',
            getattr(self.category, 'name', '') or '',
            getattr(self.manufacturer, 'name', '') or '',
            self.article or '',
            self.sku or '',
        ]
        return ' '.join(p for p in parts if p)

    def rebuild_search_vector(self):
        text = self._build_search_text()
        self.search_vector = SearchVector(Value(text), config='russian')
        self.save(update_fields=['search_vector'])

