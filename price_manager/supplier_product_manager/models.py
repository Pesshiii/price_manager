from django.db import models

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier, Discount, Manufacturer, Category
  
SP_TABLE_FIELDS = ['discounts', 'category','article', 'name', 'supplier_price', 'rrp']
SP_CHARS = ['article', 'name']
SP_FKS = ['main_product', 'category', 'supplier', 'manufacturer', 'discounts']
SP_PRICES = ['supplier_price', 'rrp']
SP_INTEGERS = ['stock']
SP_MANAGMENT = ['updated_at']

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
  category = models.ForeignKey(Category,
                               on_delete=models.SET_NULL,
                               verbose_name='Категория',
                               null=True,
                               blank=True,)
  discounts = models.ManyToManyField(Discount,
                               verbose_name='Группа скидок',
                               related_name='products')
  manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
                                   related_name='supplier_product',
                                   on_delete=models.SET_NULL,
                                   null=True,
                                   blank=True)
  stock = models.PositiveIntegerField(verbose_name='Остаток',
                              default=0)
  supplier_price = models.DecimalField(
      verbose_name='Цена поставщика в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      default=0)
  rrp = models.DecimalField(
      verbose_name='РРЦ в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      default=0)
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
         'discounts': 'Группа скидок',
         'manufacturer': 'Производитель',
         'stock': 'Остаток',
         'supplier_price': 'Цена поставщика в валюте поставщика',
         'rrp': 'РРЦ в валюте поставщика',
         }

class Setting(models.Model):
  name = models.CharField(verbose_name='Название',
                          unique=False)
  supplier = models.ForeignKey(Supplier,
                              on_delete=models.CASCADE,
                              blank=False)
  sheet_name = models.CharField(verbose_name='Название листа')
  priced_only = models.BooleanField(verbose_name='Не добавлять товары без цены поставщика',
                                    default=True)
  update_main_content = models.BooleanField(
    verbose_name='Обновлять данные по товарам (контент) в ГП',
    default=True,
  )
  add_main_products = models.BooleanField(
    verbose_name='Добавлять новые товары в ГП',
    default=True,
  )
  differ_by_name = models.BooleanField(
    verbose_name='Сопоставлять товары по названию и артикулу поставщика',
    default=True,
  )
  grouping_priority = models.PositiveIntegerField(
    verbose_name='Приоритет при группировке',
    default=0,
  )
  class Meta:
    constraints = [models.UniqueConstraint(fields=['name', 'supplier'], name='name_supplier_constraint')]

class Link(models.Model):
  setting = models.ForeignKey(Setting,
                              on_delete=models.CASCADE)
  initial = models.CharField(null=True)
  key = models.CharField(choices=LINKS)
  value = models.CharField()
  class Meta:
    constraints = [models.UniqueConstraint(fields=['setting', 'key'], name='product-field-constraint')]

class Dict(models.Model):
  link = models.ForeignKey(Link,
                           on_delete=models.CASCADE,
                           verbose_name='Столбец',
                           blank=True,
                           null=True)
  key = models.CharField(verbose_name='Если')
  value = models.CharField(verbose_name='То')
