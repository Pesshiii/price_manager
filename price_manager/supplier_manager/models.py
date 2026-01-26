from django.db import models
from mptt.models import MPTTModel, TreeForeignKey

TIME_FREQ = {'Каждый день': 1,
             'Каждую неделю': 7,
             'Каждые три недели': 21}

# Основные классы для продуктов(главных/поставщика)
  
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

SUPPLIER_SPECIFIABLE_FIELDS = ['name', 'delivery_days', 'currency', 'price_update_rate', 'stock_update_rate']

class Supplier(models.Model):
  """
  Модель Supplier представляет поставщика товаров.
  Атрибуты:
    name (CharField): Название поставщика (уникальное).
    price_updated_at (DateTimeField): Дата и время последнего обновления цены.
    stock_updated_at (DateTimeField): Дата и время последнего обновления остатка.
    delivery_days (PositiveIntegerField): Срок доставки в днях.
  Методы:
    __str__: Возвращает название поставщика.
  Meta:
    verbose_name: Человекочитаемое имя модели ("Поставщик").
  """

  name = models.CharField(verbose_name='Поставщик',
                        unique=True)
  currency = models.ForeignKey(Currency,
                               verbose_name='Валюта поставщика',
                                on_delete=models.PROTECT,
                                default=1,
                                blank=False)
  price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены', 
                                          null=True,
                                          blank=True)
  stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка', 
                                          null=True,
                                          blank=True)
  delivery_days = models.PositiveIntegerField(verbose_name='Срок доставки',
                                              default=0)
  price_update_rate = models.CharField(verbose_name='Частота обновления цен',
                                       choices=[(_, _) for _ in TIME_FREQ.keys()])
  stock_update_rate = models.CharField(verbose_name='Частота обновления остатков',
                                       choices=[(_, _) for _ in TIME_FREQ.keys()])
  msg_available = models.CharField(verbose_name="Сообщение при наличии",
                                   default="Есть в наличии")
  msg_navailable = models.CharField(verbose_name="Сообщение при отсутствии",
                                    default="Нет в наличии")
  class Meta:
    verbose_name = 'Поставщик'
    ordering = ['name']
  def __str__(self):
    return self.name
  

class Discount(models.Model):
  """
  Модель Discount представляет скидку, связанную с определённым поставщиком.
  Поля:
  - name: Название скидки.
  - supplier: Ссылка на поставщика, к которому относится скидка.
  Ограничения:
  - Уникальность сочетания названия скидки и поставщика.
  """
  
  name = models.CharField(verbose_name='Название',
                          null=False)
  supplier = models.ForeignKey(Supplier,
                              verbose_name='Поставщик',
                              null=False,
                              on_delete=models.CASCADE,
                              related_name='discounts')
  def __str__(self):
    return self.name
  class Meta:
    constraints = [models.UniqueConstraint(fields=['name', 'supplier'], name='discount_name_supplier_constraint')]

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
  

class Category(MPTTModel):
  parent = TreeForeignKey('self',
                             on_delete=models.PROTECT,
                             verbose_name='Подкатегория для',
                             related_name='children',
                             null=True,
                             blank=True)
  name = models.CharField(verbose_name='Название',
                          null=False)
  def __str__(self):
    if self.parent:
      return f'{self.parent}>{self.name}'
    else:
      return self.name
  class Meta:
    constraints = [models.UniqueConstraint(fields=['parent', 'name'], name='parent_child_constraint')]
  class MPTTMeta:
      order_insertion_by = ['name']
    