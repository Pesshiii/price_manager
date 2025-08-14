from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.core.validators import FileExtensionValidator
import typing


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
  manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
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
    
def icontains(name, value):
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

class Product(models.Model):
  supplier=models.ForeignKey(Supplier,
                             verbose_name='Поставщик',
                             on_delete=models.CASCADE,
                             null=False,
                             blank=False)
  article = models.CharField(verbose_name='Артикул поставщика',
                             null=False,
                             blank=False)
  name = models.CharField(verbose_name='Наименование',
                          null=False,
                          blank=False)
  constraint = models.UniqueConstraint(fields=['supplier','article', 'name'], name='unique_product_constraint')
  category = models.ForeignKey(Category,
                               on_delete=models.SET_NULL,
                               verbose_name='Категория',
                               null=True,
                               blank=True,)
  supplier_price = models.DecimalField(
      verbose_name='Цена поставщика',
      decimal_places=2,
      max_digits=20,
      default=0)
  manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
                                   on_delete=models.SET_NULL,
                                   null=True)
  stock = models.PositiveIntegerField(verbose_name='Остаток',
                              default=0)
  objects = ProductManager()

class MainProduct(Product):
  sku = models.CharField(verbose_name='Артикул товара',
                         unique=True)
  rmp_kzt = models.DecimalField(
      verbose_name='РРЦ в тенге',
      decimal_places=2,
      max_digits=20,
      default=0)
  weight = models.DecimalField(
      verbose_name='Вес',
      decimal_places=1,
      max_digits=8,
      null=True)
  def __str__(self):
    return self.sku
  class Meta:
    verbose_name = 'Главный продукт'
  
class SupplierProduct(Product):
  sku=models.ForeignKey(MainProduct,
                        verbose_name='sku',
                        related_name='sku_ptr',
                        on_delete=models.SET_NULL,
                        null=True,
                        blank=True)
  rmp_raw = models.DecimalField(
      verbose_name='РРЦ в валюте закупа',
      decimal_places=2,
      max_digits=20,
      default=0)
  currency = models.ForeignKey(Currency,
                               verbose_name='Валюта',
                               on_delete=models.PROTECT,
                               blank=False,
                               null=True)

# Модели для менджмента загрузки/обновления поставщиков

# Базовые данные
# Переопределяется в functions.py
LINKS = [
  (None, 'Не включать')
]

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
  link = models.CharField(choices=LINKS)
  column = models.CharField()
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