from django.db import models
from django.db.models import Q
from django.core.validators import (FileExtensionValidator, MinValueValidator, MaxValueValidator)
from django.db.models.signals import post_save
from django.dispatch import receiver

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import (SearchVectorField, SearchVector, SearchQuery, SearchRank)


import typing

# Основные классы для продуктов(главных/поставщика)

class Supplier(models.Model):
  name = models.CharField(verbose_name='Поставщик',
                        unique=True)
  class Meta:
    verbose_name = 'Поставщик'
  def __str__(self):
    return self.name

class Manufacturer(models.Model):
  name = models.CharField(verbose_name='Производитель',
                        unique=True)
  class Meta:
    verbose_name = 'Производитель'
  def __str__(self):
    return self.name
  
class ManufacturerDict(models.Model):
  '''
  Подвязывает производителя потом\\
  По этому словарю выбирается производитель
  '''
  manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
                                   related_name='md_manufacturer_ptr',
                                   on_delete=models.CASCADE)
  name = models.CharField(verbose_name='Вариация',
                          unique=True,
                          null=False)
  class Meta:
    verbose_name = 'Словарь Производителя'
  def __str__(self):
    return f'{self.name}({self.manufacturer.name})'
  
class Currency(models.Model):
  name = models.CharField(verbose_name='Название',
                          unique=True,
                          null=False)
  value = models.DecimalField(verbose_name='Тенге',
                               max_digits=1000,
                               null=False,
                               decimal_places=2)
  def __str__(self):
    return self.name

class Category(models.Model):
  parent = models.ForeignKey('self',
                             on_delete=models.PROTECT,
                             verbose_name='Подкатегория для',
                             null=True,
                             blank=True)
  name = models.CharField(verbose_name='Название',
                          null=False)
  constraint = models.UniqueConstraint(fields=['parent', 'name'], name='parent_child_constraint')
  def __str__(self):
    if self.parent:
      return f'{self.parent}>{self.name}'
    else:
      return self.name
    

class Discount(models.Model):
  name = models.CharField(verbose_name='Название',
                          null=False,
                          unique=True)
  def __str__(self):
    return self.name
    
# Модели для применения наценок

class PriceManager(models.Model):
  '''
  Используется для нацепки класса наценок на товары\\
  '''
  name = models.CharField(verbose_name='Название',
                          unique=True)
  supplier = models.ForeignKey(Supplier,
                               on_delete=models.CASCADE,
                               verbose_name='Поставщик',
                               related_name='pm_supplier_ptr',
                               unique=False,
                               null=True)
  discount = models.ForeignKey(Discount,
                               on_delete=models.CASCADE,
                               verbose_name='Группа скидок',
                               related_name='pm_discount_ptr',
                               unique=False,
                               null=True,
                               blank=True)
  source = models.CharField(verbose_name='От какой цены считать',
                                 choices=[
                                  ('rmp_kzt', 'РРЦ поставщика в тенге'),
                                  ('supplier_price_kzt', 'Цена поставщика в тенге'),
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1')])
  dest = models.CharField(verbose_name='Какую цену считать',
                                 choices=[
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1')])
  price_from = models.DecimalField(
      verbose_name='Цена от',
      decimal_places=2,
      max_digits=20,
      validators=[MinValueValidator(0)],
      null=True,
      blank=True)
  price_to = models.DecimalField(
      verbose_name='Цена до',
      decimal_places=2,
      max_digits=20,
      validators=[MinValueValidator(0)],
      null=True,
      blank=True)
  markup = models.DecimalField(
      verbose_name='Накрутка',
      decimal_places=2,
      max_digits=5,
      validators=[MinValueValidator(-100), MaxValueValidator(100)],
      default=0)
  increase = models.DecimalField(
      verbose_name='Надбавка',
      decimal_places=2,
      max_digits=20,
      default=0)
  def __str__(self):
    return self.name
    
def icontains(name, value):
  '''Иммитирует _icontains для sqlite3(потом будет убрано) '''
  return  Q(
    Q(**{f"{name}__icontains": value}) |
    Q(**{f"{name}__icontains": value.lower()}) |
    Q(**{f"{name}__icontains": value.upper()}) |
    Q(**{f"{name}__icontains": value.capitalize()}))

class ProductQuerySet(models.QuerySet):
  def search_fields(self, request: typing.Dict[str, str]):
    query = Q()
    s_query = Q()
    search = [chunk for chunk in request.get('search', '').split() if not chunk == '']
    for field in self.model._meta.fields:
        value = request.get(field.name, None)
        if not value:
          continue
        if field.get_internal_type() in {"CharField", "TextField"}:
          query &= icontains(f"{field.name}", value)
        else:
          query &= Q(**{field.name: value})
    for field in self.model._meta.fields:
      if not field.get_internal_type() in {"CharField", "TextField"} and not field.is_relation:
        continue
      for chunk in search:
        s_query |= icontains(f"{field.name}{'__name'*(field.is_relation)}", chunk)
    return self.filter(s_query).filter(query)



class ProductManager(models.Manager):
  def get_queryset(self):
    return ProductQuerySet(self.model, using=self._db)
  def search_fields(self, request: typing.Dict[str, str]):
    return self.get_queryset().search_fields(request)

MP_FIELDS = ['category', 'supplier', 'name', 'manufacturer', 'stock', 'm_price']


class MainProduct(models.Model):
  objects = ProductManager()
  sku = models.CharField(verbose_name='Артикул товара',
                         null=True,
                         blank=True,
                         unique=False)
  supplier=models.ForeignKey(Supplier,
                             verbose_name='Поставщик',
                             related_name='mp_supplier_ptr',
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
                               null=True,
                               blank=True,)
  discount = models.ForeignKey(Discount,
                               on_delete=models.SET_NULL,
                               verbose_name='Группа скидок',
                               null=True,
                               blank=True)
  manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
                                   related_name='mp_manufacturer_ptr',
                                   on_delete=models.SET_NULL,
                                   null=True,
                                   blank=True)
  stock = models.PositiveIntegerField(verbose_name='Остаток',
                              default=0)
  weight = models.DecimalField(
      verbose_name='Вес',
      decimal_places=1,
      max_digits=8,
      default=0)
  prime_cost = models.DecimalField(
      verbose_name='Себестоимость',
      decimal_places=2,
      max_digits=20,
      default=0)
  wholesale_price = models.DecimalField(
      verbose_name='Оптовая цена',
      decimal_places=2,
      max_digits=20,
      default=0)
  basic_price = models.DecimalField(
      verbose_name='Базовая цена',
      decimal_places=2,
      max_digits=20,
      default=0)
  m_price = models.DecimalField(
      verbose_name='Цена ИМ',
      decimal_places=2,
      max_digits=20,
      default=0)
  wholesale_price_extra = models.DecimalField(
      verbose_name='Оптовая цена доп.',
      decimal_places=2,
      max_digits=20,
      default=0)
  price_manager = models.ForeignKey(
    PriceManager,
    verbose_name='Наценка',
    related_name='mp_price_manager_ptr',
    on_delete=models.SET_NULL,
    null=True,
    blank=True
  )
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
  updated_at = models.DateTimeField(verbose_name='Последнее обновление',
                                    auto_now=True)
  search_vector = SearchVectorField(null=True, editable=False, unique=False, verbose_name="Вектор поиска")
  def __str__(self):
    return self.sku
  class Meta:
    verbose_name = 'Главный продукт'
    constraints = [
      models.UniqueConstraint(
        fields=['supplier', 'article', 'name'],
        name='mp_uniqe_supplier_article_name'
      )
    ]
    indexes = [
      GinIndex(fields=['search_vector']),
    ]
  
SP_FIELDS = ['main_product', 'category', 'supplier','article', 'name', 'manufacturer', 'supplier_price_kzt', 'rmp_kzt']
PRICE_FIELDS = ['supplier_price', 'supplier_price_kzt', 'rmp_raw', 'rmp_kzt']

class SupplierProduct(models.Model):
  main_product=models.ForeignKey(MainProduct,
                        verbose_name='sku',
                        related_name='sp_main_product_ptr',
                        on_delete=models.SET_NULL,
                        null=True,
                        blank=True)
  
  objects = ProductManager()
  supplier=models.ForeignKey(Supplier,
                             verbose_name='Поставщик',
                             related_name='sp_supplier_ptr',
                             on_delete=models.CASCADE,
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
                               null=True,
                               blank=True,)
  discount = models.ForeignKey(Discount,
                               on_delete=models.SET_NULL,
                               verbose_name='Группа скидок',
                               null=True,
                               blank=True)
  manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
                                   related_name='sp_manufacturer_ptr',
                                   on_delete=models.SET_NULL,
                                   null=True,
                                   blank=True)
  stock = models.PositiveIntegerField(verbose_name='Остаток',
                              default=0)
  supplier_price = models.DecimalField(
      verbose_name='Цена поставщика',
      decimal_places=2,
      max_digits=20,
      default=0)
  supplier_price_kzt = models.DecimalField(
      verbose_name='Цена поставщика в тенге',
      decimal_places=2,
      max_digits=20,
      default=0)
  rmp_raw = models.DecimalField(
      verbose_name='РРЦ в валюте закупа',
      decimal_places=2,
      max_digits=20,
      default=0)
  rmp_kzt = models.DecimalField(
      verbose_name='РРЦ в тенге',
      decimal_places=2,
      max_digits=20,
      default=0)
  currency = models.ForeignKey(Currency,
                               verbose_name='Валюта',
                               related_name='sp_currency_ptr',
                               on_delete=models.PROTECT,
                               blank=False,
                               null=True)
  updated_at = models.DateTimeField(verbose_name='Последнее обновление',
                                    auto_now=True)
  
  class Meta:
    constraints = [
      models.UniqueConstraint(
        fields=['supplier', 'article', 'name'],
        name='sp_uniqe_supplier_article_name'
      )
    ]

# Модели для менджмента загрузки/обновления поставщиков

# Базовые данные
LINKS = {'': 'Не включать',
         'article': 'Артикул поставщика',
         'name': 'Название',
         'category': 'Категория',
         'discount': 'Группа скидок',
         'manufacturer': 'Производитель',
         'stock': 'Остаток',
         'supplier_price': 'Цена поставщика',
         'supplier_price_kzt': 'Цена поставщика в тенге',
         'rmp_raw': 'РРЦ в валюте закупа',
         'rmp_kzt': 'РРЦ в тенге',
         }

class Setting(models.Model):
  name = models.CharField(verbose_name='Название',
                          unique=False)
  supplier = models.ForeignKey(Supplier,
                              on_delete=models.CASCADE,
                              blank=False)
  sheet_name = models.CharField(verbose_name='Название листа')
  priced_only = models.BooleanField(verbose_name='Не включать поля без цены',
                                    default=True)
  id_as_sku = models.BooleanField(verbose_name='Использывать артикул как SKU',
                                  default=True)
  currency = models.ForeignKey(Currency,
                               verbose_name='Валюта',
                               on_delete=models.PROTECT,
                               blank=False)
  constraint = models.UniqueConstraint(fields=['name', 'supplier'], name='name_supplier_constraint')

class Link(models.Model):
  setting = models.ForeignKey(Setting,
                              on_delete=models.CASCADE)
  initial = models.CharField(null=True)
  key = models.CharField(choices=LINKS)
  value = models.CharField()
  constraint = models.UniqueConstraint(fields=['setting', 'link'], name='product-field-constraint')

class Dict(models.Model):
  link = models.ForeignKey(Link,
                           on_delete=models.CASCADE,
                           verbose_name='Столбец',
                           blank=True,
                           null=True)
  key = models.CharField(verbose_name='Если')
  value = models.CharField(verbose_name='То')

# Обработка файлов

class FileModel(models.Model):
  file = models.FileField(verbose_name='Файл',
                         validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx'])],
                         null=False)