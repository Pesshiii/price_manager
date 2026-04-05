from django.db import models
from django.contrib.postgres.search import SearchVectorField, SearchVector 
from django.contrib.postgres.indexes import GinIndex
from django.db.models import Value, OuterRef, Subquery, Q, F, Sum
from django.db.models.functions import Concat
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from supplier_manager.models import Supplier, Category, Manufacturer
   
MP_TABLE_FIELDS = ['article', 'supplier', 'name', 'manufacturer','prime_cost', 'stock']
MP_PRICES = ['prime_cost', 'wholesale_price', 'basic_price', 'm_price', 'wholesale_price_extra', 'discount_price']
PRICE_TYPES = {
  None : 'Не указано',
  'fixed_price': 'Фиксированная цена',
  'rrp': 'РРЦ в валюте поставщика',
  'supplier_price': 'Цена поставщика в валюте поставщика',
  'basic_price': 'Базовая цена',
  'prime_cost': 'Себестоимость',
  'm_price': 'Цена ИМ',
  'wholesale_price': 'Оптовая цена',
  'wholesale_price_extra': 'Оптовая цена1',
  'discount_price': 'Цена со скидкой',
}


class MainProduct(models.Model):
  class Meta:
    verbose_name = 'Главный продукт'
    ordering = ['id']
    constraints = [
      models.UniqueConstraint(
        fields=['supplier', 'article', 'name'],
        name='mp_unique_supplier_article_name'
      )
    ]
    indexes = [
      GinIndex(fields=['search_vector']),
    ]
  sku = models.CharField(verbose_name='Артикул товара',
                         null=True,
                         blank=True,
                         unique=False)
  supplier=models.ForeignKey(Supplier,
                             verbose_name='Поставщик',
                             related_name='main_products',
                             on_delete=models.PROTECT,
                             null=False,
                             blank=False)
  article = models.CharField(verbose_name='Артикул поставщика',
                             null=False,
                             blank=False)
  name = models.CharField(verbose_name='Название',
                          null=False,
                          blank=False)
  category = models.ForeignKey(Category,
                               on_delete=models.SET_NULL,
                               verbose_name='Категория',
                               related_name='mainproducts',
                               null=True,
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
  discount_price = models.DecimalField(
      verbose_name='Цена со скидкой',
      decimal_places=2,
      max_digits=20,
      null=True)
  length = models.DecimalField(verbose_name='Длина',
                               max_digits=10,
                               decimal_places=2,
                               default=0)
  width = models.DecimalField(verbose_name='Ширина',
                               max_digits=10,
                               decimal_places=2,
                               default=0)
  depth = models.DecimalField(verbose_name='Глубина',
                               max_digits=10,
                               decimal_places=2,
                               default=0)
  price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены',
                                    null=True)
  stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка',
                                    null=True)
  search_vector = SearchVectorField(null=True, editable=False, unique=False, verbose_name="Вектор поиска")
  description = models.TextField(
    verbose_name="Описание",
    null=True,
    blank=True)
  def __str__(self):
    return self.sku if self.sku else 'Не указан'
  def _build_search_text(self) -> str:
    """Собираем строку для поиска без join-ов."""
    parts = [
        self.sku or "",
        self.article or "",
        self.name or "",
        self.description or "",
        ' '.join(self.category.get_ancestors(include_self=True).values_list('name', flat=True) if self.category else ""),
        getattr(self.supplier, "name", ""),
        getattr(self.manufacturer, "name", ""),
    ]
    return " ".join(parts)
  def rebuild_search_vector(self):
    """Обновляет search_vector без join-полей (через константу)."""
    text = self._build_search_text()
    MainProduct.objects.filter(pk=self.pk).update(
        search_vector=SearchVector(Value(text), config='russian')
    )
    
  def save(self, *args, **kwargs):
    super().save(*args, **kwargs)
    self.rebuild_search_vector()
  

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

DUPLICATE_LOOKUPS={
        'name':{
          'verbose_name':'Имя содержит',
          'field':'name',
          },
        'article':{
          'verbose_name':'Артикул',
          'field':'article',
          },
        'supplier__id':{
          'verbose_name':'Поставщик(по id)',
          'field':'supplier__id',
          }
    }
