from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from supplier_manager.models import Supplier

from decimal import Decimal
   
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
    """Строка поставщика: его остаток и цены на товар (product.Product).

    Поиск, название из PIM, бренд и категории живут на Product. Собственные
    search_vector, description, categories, manufacturer и габариты удалены в
    Phase 2b (.claude/shift-to-product-brief.md, D12/D13).
    """
    class Meta:
        verbose_name = 'Главный продукт'
        ordering = ['id']
        constraints = [
            # Строка набора — одна на товар: её себестоимость пишет
            # product.services.set_rows, и двум таким строкам нечем различаться.
            models.UniqueConstraint(fields=['product'], condition=models.Q(is_set=True),
                                    name='mainproduct_one_set_row_per_product'),
        ]
    product = models.ForeignKey('product.Product',
                              verbose_name='Товар PIM',
                              related_name='main_products',
                              on_delete=models.SET_NULL,
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
    stock = models.PositiveIntegerField(verbose_name='Остаток',
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
    price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены',
                                      null=True)
    stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка',
                                      null=True)
    # Строка ГП набора: без поставщика, себестоимость — сумма себестоимостей
    # комплектующих (product.services.set_rows), руками не правится; остальные
    # цены — как у любой строки ГП, наценками. Создаётся сама для каждого набора.
    is_set = models.BooleanField(verbose_name='Строка набора', default=False)
    def __str__(self)->str:
        return f'{self.sku}' if self.sku is not None else 'Не указан'
    def price_list(self) -> list[tuple[str, str, Decimal]]:
        """Заполненные цены товара — [(имя поля, подпись, значение), …] в порядке MP_PRICES."""
        return [
            (name, self._meta.get_field(name).verbose_name, getattr(self, name))
            for name in MP_PRICES
            if getattr(self, name) is not None
        ]
    @property
    def has_supplier_price_list(self) -> bool:
        """Строка пришла из прайса поставщика: её поставщика и артикул держит импорт."""
        return self.supplier_id is not None and self.supplierproducts.exists()
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

