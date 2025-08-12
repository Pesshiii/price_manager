from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.core.validators import FileExtensionValidator



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

class MainProduct(Product):
  sku = models.CharField(verbose_name='Артикуль товара',
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
    return self.name
  class Meta:
    verbose_name = 'Главный продукт'
  
class SupplierProductManager(models.Manager):
  def search_all(self, search):
    chunks = search.split(' ')
    fields = ['sku', 'supplier', 'manufacturer']
    query = Q()
    annotations = {
      f'lower_{field}_name': Lower(f'{field}__name') for field in fields
    }
    annotations['lower_name'] = Lower('name')
    queryset = self.get_queryset().annotate(**annotations)
    for chunk in chunks:
      for field in fields:
          query |= Q(**{f"lower_{field}_name__icontains": chunk.lower()})
      query |= Q(lower_name__icontains=chunk.lower())
    return queryset.filter(query)
  def search_fields(self, request):
    query = Q()
    search = request.get('search', '')
    queryset = self.search_all(search)
    annotations = {}
    for field in self.model._meta.fields:
        value = request.get(field.name, '').lower()
        if not value == '':
          if field.is_relation:
            annotations[f'lower_{field.name}_name'] = Lower(f'{field.name}__name')
            query &= Q(**{f"lower_{field.name}_name__icontains": value})
          else:
            annotations[f'lower_{field.name}'] = Lower(f'{field.name}')
            query &= Q(**{f"lower_{field.name}__icontains": value})
    return queryset.filter(query)

class SupplierProduct(Product):
  sku=models.ForeignKey(MainProduct,
                        verbose_name='sku',
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
  objects = SupplierProductManager()

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

# Обработка файлов

class FileModel(models.Model):
  file = models.FileField(verbose_name='Файл',
                         validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx'])],
                         null=False)