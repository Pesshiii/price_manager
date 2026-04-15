from django.db import models
from django.core.validators import FileExtensionValidator
from django.conf import settings


from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier, Discount, Manufacturer, Category

from decimal import Decimal
  
SP_TABLE_FIELDS = ['article', 'name', 'manufacturer', 'supplier_price', 'rrp', 'discount', ]
SP_PRICES = ['supplier_price', 'rrp', 'discount_price']
SP_NUMBERS = ['supplier_price', 'rrp', 'stock', 'discount_price']

class SupplierProduct(models.Model):
  main_product=models.ForeignKey(MainProduct,
                        verbose_name='sku',
                        related_name='supplierproducts',
                        on_delete=models.SET_NULL,
                        null=True,
                        blank=True)
  supplier=models.ForeignKey(Supplier,
                             verbose_name='Поставщик',
                             related_name='supplierproducts',
                             on_delete=models.CASCADE,
                             null=False,
                             blank=False)
  article = models.CharField(verbose_name='Артикул поставщика',
                             null=False,
                             blank=False)
  name = models.CharField(verbose_name='Название',
                          null=False,
                          blank=False)
  description = models.TextField(
    verbose_name="Описание",
    null=True,
    blank=True)
  category = models.ForeignKey(Category,
                               on_delete=models.SET_NULL,
                               verbose_name='Категория',
                               related_name='supplierproducts',
                               null=True,
                               blank=True)
  manufacturer = models.ForeignKey(Manufacturer,
                                   verbose_name='Производитель',
                                   related_name='supplierproducts',
                                   on_delete=models.SET_NULL,
                                   null=True,
                                   blank=True)
  discount = models.ForeignKey(Discount,
                                verbose_name='Группа скидок',
                                related_name='supplierproducts',
                                on_delete=models.SET_NULL,
                                null=True,
                                blank=True)
  stock = models.PositiveIntegerField(verbose_name='Остаток',
      null=True,
      blank=True)
  supplier_price = models.DecimalField(
      verbose_name='Цена поставщика в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      null=True,
      blank=True)
  rrp = models.DecimalField(
      verbose_name='РРЦ в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      null=True,
      blank=True)
  discount_price = models.DecimalField(
      verbose_name='Цена со скидкой в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      null=True,
      blank=True)
  updated_at = models.DateTimeField(verbose_name='Последнее обновление',
                                    auto_now=True,
      blank=True)
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
         'description': 'Описание',
         'category': 'Категория',
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
  ignore_name = models.BooleanField(
    verbose_name='Игнорировать название при создании',
    default=False)
  create_new = models.BooleanField(verbose_name='Создавать если нет',
                                   default=False)
  index_row = models.IntegerField(verbose_name='Ряд для индексации',
                                   null=True, blank=True)
  class Meta:
    constraints = [models.UniqueConstraint(fields=['name', 'supplier'], name='name_supplier_constraint')]
  def __str__(self):
    return self.name
  def is_bound(self) -> bool:
    for link in self.links.filter(value=''):
      link.value = None
      link.save()
    if not self.links.filter(key='article', value__isnull=False).exists():
      return False
    if self.create_new and not self.links.filter(key='name', value__isnull=False):
      return False
    return True

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
  STATUS_QUEUED = 0
  STATUS_RUNNING = 2
  STATUS_SUCCESS = 1
  STATUS_ERROR = -1

  STATUS_CHOICES = [
    (STATUS_QUEUED, 'В очереди'),
    (STATUS_RUNNING, 'В процессе'),
    (STATUS_SUCCESS, 'Успешно'),
    (STATUS_ERROR, 'Ошибка'),
  ]

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
                               choices=STATUS_CHOICES,
                               default=STATUS_QUEUED,
                               blank=True)
  logs = models.CharField(verbose_name="Журнал загрузки", null=True, blank=True)


class CopySupplierProductsToMainRun(models.Model):
  STATUS_STARTED = "started"
  STATUS_SUCCESS = "success"
  STATUS_ERROR = "error"

  STATUS_CHOICES = [
    (STATUS_STARTED, "Выполняется"),
    (STATUS_SUCCESS, "Успешно"),
    (STATUS_ERROR, "Ошибка"),
  ]

  supplier = models.ForeignKey(
    Supplier,
    verbose_name="Поставщик",
    related_name="copy_to_main_runs",
    on_delete=models.CASCADE,
  )
  user = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    verbose_name="Пользователь",
    related_name="copy_to_main_runs",
    on_delete=models.CASCADE,
  )
  status = models.CharField(
    verbose_name="Статус",
    max_length=16,
    choices=STATUS_CHOICES,
    default=STATUS_STARTED,
    db_index=True,
  )
  filter_params = models.JSONField(verbose_name="Параметры фильтра", default=dict, blank=True)
  processed_count = models.PositiveIntegerField(verbose_name="Обработано записей", default=0)
  created_count = models.PositiveIntegerField(verbose_name="Создано новых записей ГП", default=0)
  updated_links_count = models.PositiveIntegerField(verbose_name="Обновлено связей", default=0)
  error = models.TextField(verbose_name="Ошибка", null=True, blank=True)
  started_at = models.DateTimeField(verbose_name="Начало", auto_now_add=True)
  finished_at = models.DateTimeField(verbose_name="Окончание", null=True, blank=True)

  class Meta:
    ordering = ("-started_at",)
    verbose_name = "Копирование товаров поставщика в ГП"
    verbose_name_plural = "Копирование товаров поставщика в ГП"
