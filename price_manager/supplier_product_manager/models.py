from django.db import models
from django.core.validators import FileExtensionValidator


from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier, Discount, Manufacturer, Category

from decimal import Decimal
  
SP_TABLE_FIELDS = ['article', 'name', 'manufacturer', 'supplier_price', 'rrp', 'discount', ]
SP_PRICES = ['supplier_price', 'rrp', 'discount_price']
SP_NUMBERS = ['supplier_price', 'rrp', 'stock', 'discount_price']

class SupplierProduct(models.Model):
  main_product=models.ForeignKey(MainProduct,
                        verbose_name='sku',
                        related_name='supplier_products',
                        on_delete=models.SET_NULL,
                        null=True,
                        blank=True)
  supplier=models.ForeignKey(Supplier,
                             verbose_name='Поставщик',
                             related_name='supplier_product',
                             on_delete=models.CASCADE,
                             null=False,
                             blank=False)
  article = models.CharField(verbose_name='Артикул поставщика',
                             null=False,
                             blank=False)
  name = models.CharField(verbose_name='Название',
                          null=False,
                          blank=False)
  manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
                                   related_name='supplier_products',
                                   on_delete=models.SET_NULL,
                                   null=True,
                                   blank=True)
  discount = models.ForeignKey(Discount,
                                verbose_name='Группа скидок',
                                related_name='supplier_products',
                                on_delete=models.SET_NULL,
                                null=True,
                                blank=True)
  stock = models.PositiveIntegerField(verbose_name='Остаток',
      null=True)
  supplier_price = models.DecimalField(
      verbose_name='Цена поставщика в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      null=True)
  rrp = models.DecimalField(
      verbose_name='РРЦ в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      null=True)
  discount_price = models.DecimalField(
      verbose_name='Цена со скидкой в валюте поставщика',
      decimal_places=2,
      max_digits=20,
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
         'manufacturer': 'Производитель',
         'discount': 'Группа скидок',
         'stock': 'Остаток',
         'supplier_price': 'Цена поставщика в валюте поставщика',
         'rrp': 'РРЦ в валюте поставщика',
         'discount_price': 'Цена со скидкой в валюте поставщика',
         }

class Setting(models.Model):
  name = models.CharField(verbose_name='Название',
                          unique=False,
                          null=False)
  supplier = models.ForeignKey(Supplier,
                               related_name='settings',
                              on_delete=models.CASCADE,
                              blank=False)
  sheet_name = models.CharField(verbose_name='Название листа')
  priced_only = models.BooleanField(verbose_name='Не включать поля без цены',
                                    default=True)
  differ_by_name = models.BooleanField(verbose_name='Различать по имени',
                                       default=True)
  class Meta:
    constraints = [models.UniqueConstraint(fields=['name', 'supplier'], name='name_supplier_constraint')]
  def __str__(self):
    return self.name
  def is_bound(self) -> bool:
    for link in self.links.filter(value=''):
      link.value = None
      link.save()
    return self.links.filter(key='article', value__isnull=False).exists() and self.links.filter(key='name', value__isnull=False).exists()

class Link(models.Model):
  class Meta:
    constraints = [models.UniqueConstraint(fields=['setting', 'key'], name='link-field-constraint')]
  setting = models.ForeignKey(Setting,
                              on_delete=models.CASCADE,
                              related_name='links')
  initial = models.CharField(null=True)
  key = models.CharField(choices=LINKS)
  value = models.CharField(null=True)
  def __str__(self):
    return f'{self.key}<--->{self.value}({self.initial})'
  

class DictItem(models.Model):
  link = models.ForeignKey(Link,
                           on_delete=models.CASCADE,
                           verbose_name='Столбец',
                           related_name='dicts',
                           blank=True,
                           null=True)
  key = models.CharField(verbose_name='Если')
  value = models.CharField(verbose_name='То')
  class Meta:
    constraints = [models.UniqueConstraint(fields=['link', 'key', 'value'], name='link-dict-constraint')]

def setting_dir(instance, filename):
  return f'setting_{instance.setting.supplier.pk}/{filename}'

class SupplierFile(models.Model):
  setting = models.ForeignKey(Setting,
                              null=True,
                              blank=True,
                              verbose_name="Настройка",
                              related_name="supplierfiles",
                              on_delete=models.CASCADE)
  file = models.FileField(verbose_name='Файл',
                          upload_to=setting_dir,
                          max_length=255,
                          validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm'])],
                          null=False)
  status = models.IntegerField(verbose_name="Статус загрузки",
                               choices=[
                                 (0, 'Не загружен'),
                                 (1, 'Загружен'),
                                 (-1, 'Ошибка')
                               ],
                               default=0,
                               blank=True)
  logs = models.CharField(verbose_name="Журнал загрузки", null=True, blank=True)