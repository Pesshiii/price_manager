from django.contrib.admin import site
from django.db import models
from django.contrib.postgres.search import SearchVectorField, SearchVector 
from django.contrib.postgres.indexes import GinIndex
from django.db.models import Value, OuterRef, Subquery, Q, F, Sum
from django.db.models.functions import Concat
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from supplier_manager.models import Supplier, Category, Manufacturer

from decimal import Decimal
   
MP_TABLE_FIELDS = ['article', 'supplier', 'name', 'manufacturer','prime_cost', 'stock']
MP_PRICES = [
    'prime_cost', 
    'wholesale_price', 
    'basic_price', 
    'm_price', 
    'wholesale_price_extra', 
    'discount_price', 
    'kaspi_price'
]
MP_IMPORTABLES = ['main_photo_url']
PRICE_TYPES = {
    None : 'Не указано',
    'fixed_price': 'Фиксированная цена',
    'rrp': 'РРЦ в валюте поставщика',
    'supplier_price': 'Цена поставщика в валюте поставщика',
    'basic_price': 'Базовая цена',
    'prime_cost': 'Себестоимость',
    'm_price': 'Цена ИМ',
    'kaspi_price': 'Цена Каспи',
    'wholesale_price': 'Оптовая цена',
    'wholesale_price_extra': 'Оптовая цена1',
    'discount_price': 'Цена со скидкой',
}


class MainProduct(models.Model):
    class Meta:
        verbose_name = 'Главный продукт'
        ordering = ['id']
        indexes = [
          GinIndex(fields=['search_vector']),
        ]
    pim_id = models.CharField(verbose_name='Id для системы Pim',
                              null=True,
                              blank=True)
    sku = models.CharField(verbose_name='Артикул товара',
                         null=True,
                         blank=True,
                         unique=False)
    supplier=models.ForeignKey(Supplier,
                             verbose_name='Поставщик',
                             related_name='main_products',
                             on_delete=models.PROTECT,
                             null=True,
                             blank=True)
    article = models.CharField(verbose_name='Артикул поставщика',
                             null=False,
                             blank=False)
    name = models.CharField(verbose_name='Название',
                          null=False,
                          blank=False)
    categories = models.ManyToManyField(Category,
                               verbose_name='Категории',
                               related_name='mainproducts',
                               blank=True)
    manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
                                   related_name='mp_manufacturer_ptr',
                                   on_delete=models.SET_NULL,
                                   null=True,
                                   blank=True)
    stock = models.PositiveIntegerField(verbose_name='Остаток',
                                      null=True)
    weight = models.DecimalField(
        verbose_name='Вес',
        decimal_places=1,
        max_digits=8,
        null=True)
    prime_cost = models.DecimalField(
        verbose_name='Себестоимость',
        decimal_places=2,
        max_digits=20,
        null=True)
    wholesale_price = models.DecimalField(
        verbose_name='Оптовая цена',
        decimal_places=2,
        max_digits=20,
        null=True)
    basic_price = models.DecimalField(
        verbose_name='Базовая цена',
        decimal_places=2,
        max_digits=20,
        null=True)
    m_price = models.DecimalField(
        verbose_name='Цена ИМ',
        decimal_places=2,
        max_digits=20,
        null=True)
    wholesale_price_extra = models.DecimalField(
        verbose_name='Оптовая цена доп.',
        decimal_places=2,
        max_digits=20,
        null=True)
    kaspi_price = models.DecimalField(
            verbose_name='Цена Каспи',
            decimal_places=2,
            max_digits=20,
            null=True)
    discount_price = models.DecimalField(
        verbose_name='Цена со скидкой',
        decimal_places=2,
        max_digits=20,
        null=True)
    length = models.DecimalField(verbose_name='Длина',
                                max_digits=10,
                                decimal_places=2,
                                default=Decimal(0))
    width = models.DecimalField(verbose_name='Ширина',
                                 max_digits=10,
                                 decimal_places=2,
                                 default=Decimal(0))
    depth = models.DecimalField(verbose_name='Глубина',
                                 max_digits=10,
                                 decimal_places=2,
                                 default=Decimal(0))
  
    price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены',
                                      null=True)
    stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка',
                                      null=True)
    search_vector = SearchVectorField(null=True, editable=False, unique=False, verbose_name="Вектор поиска")
    description = models.TextField(
      verbose_name="Описание",
      null=True,
      blank=True)
    def __str__(self)->str:
        return f'{self.sku}' if self.sku is not None else 'Не указан'
    def price_list(self) -> list[tuple[str, str, Decimal]]:
        """Заполненные цены товара — [(имя поля, подпись, значение), …] в порядке MP_PRICES."""
        return [
            (name, self._meta.get_field(name).verbose_name, getattr(self, name))
            for name in MP_PRICES
            if getattr(self, name) is not None
        ]
    def _build_searchvector(self) -> SearchVector:
        """Собираем строку для поиска без join-ов."""
        from main_product_manager.utils import _resolve_pim_id, get_pim_data
        if self.pim_id is None:
            _resolve_pim_id(self)
        pim_product = get_pim_data(self.pim_id) or {}
        # Значения, а не field references ("supplier__name") - bulk_update()/update()
        # не допускают joined-полей в выражении SET.
        supplier_name = self.supplier.name if self.supplier_id else ''
        manufacturer_name = self.manufacturer.name if self.manufacturer_id else ''
        vector = (
            SearchVector(Value(''.join(pim_product.get('categoriesNames', {}).values())), weight='A', config='russian') +
            SearchVector(Value(''.join(pim_product.get('tag', []))), weight='A', config='russian') +
            SearchVector(Value(pim_product.get('name', '')), weight='A', config='russian') +
            SearchVector(Value(pim_product.get('description', '')), weight='C', config='russian') +
            SearchVector(Value(pim_product.get('longDescription', '')), weight='C', config='russian') +
            SearchVector('sku', weight='B', config='russian')+
            SearchVector('article', weight='B', config='russian') +
            SearchVector('description', weight='D', config='russian')+
            SearchVector(Value(supplier_name), weight='C', config='russian') +
            SearchVector(Value(manufacturer_name), weight='C', config='russian')
        )
        return vector
    def rebuild_search_vector(self):
        """Обновляет search_vector без join-полей (через константу)."""
        MainProduct.objects.filter(pk=self.pk).update(
            search_vector=self._build_searchvector()
        )
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
  

class MainProductLog(models.Model):
    update_time = models.DateTimeField(verbose_name='Дата',
                                   auto_now_add=True)
    main_product = models.ForeignKey(MainProduct,
                                   verbose_name='Товар',
                                   on_delete=models.CASCADE, 
                                   related_name='mp_log')
    price = models.DecimalField(
        verbose_name='Цена',
        decimal_places=2,
        max_digits=20,
        null=True)
    price_type = models.CharField(verbose_name='Тип цены',
                                  null=True,
                                  choices=[
                                    (None, '----'),
                                    ('basic_price', 'Базовая цена'),
                                    ('prime_cost', 'Себестоимость'),
                                    ('m_price', 'Цена ИМ'),
                                    ('wholesale_price', 'Оптовая цена'),
                                    ('wholesale_price_extra', 'Оптовая цена1')])
    stock = models.PositiveIntegerField(verbose_name='Остаток',
                                        null=True)
    class Meta:
        verbose_name = 'Изменения Главных продуктов'
        constraints = []
        ordering = ['-update_time']

