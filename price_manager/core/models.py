from django.db import models
from django.db.models import Q
from django.core.validators import (FileExtensionValidator, MinValueValidator, MaxValueValidator)
from django.db.models.signals import post_save
from django.dispatch import receiver

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import (SearchVectorField, SearchVector, SearchQuery, SearchRank)
from django.db.models import Value

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
  price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены', 
                                          null=True,
                                          blank=True)
  currency = models.ForeignKey(Currency,
                               verbose_name='Валюта поставщика',
                                on_delete=models.PROTECT,
                                default=1,
                                blank=False)
  stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка', 
                                          null=True,
                                          blank=True)
  delivery_days = models.PositiveIntegerField(verbose_name='Срок доставки',
                                              default=0)
  price_update_rate = models.CharField(verbose_name='Частота обновления цен',
                                       choices=[(_, _) for _ in TIME_FREQ.keys()])
  stock_update_rate = models.CharField(verbose_name='Частота обновления остатков',
                                       choices=[(_, _) for _ in TIME_FREQ.keys()])
  class Meta:
    verbose_name = 'Поставщик'
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


class Category(models.Model):
  parent = models.ForeignKey('self',
                             on_delete=models.PROTECT,
                             verbose_name='Подкатегория для',
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
    
    
# Модели для применения наценок

class PriceManager(models.Model):
  """
  Модель PriceManager предназначена для управления ценами и скидками товаров от различных поставщиков.
  Атрибуты:
    name (CharField): Название менеджера цен. Должно быть уникальным.
    supplier (ForeignKey): Ссылка на поставщика (Supplier). При удалении поставщика связанные менеджеры цен также удаляются.
    discounts (ManyToManyField): Группы скидок, связанные с менеджером цен.
    source (CharField): Источник цены, от которой производится расчет (выбор из предопределённых вариантов).
    dest (CharField): Целевая цена, которую необходимо рассчитать (выбор из предопределённых вариантов).
    price_from (DecimalField): Нижняя граница цены для применения менеджера цен.
    price_to (DecimalField): Верхняя граница цены для применения менеджера цен.
    markup (DecimalField): Процентная накрутка на цену (от -100 до 100).
    increase (DecimalField): Фиксированная надбавка к цене.
  Методы:
    __str__: Возвращает название менеджера цен.
  """
  
  name = models.CharField(verbose_name='Название',
                          unique=True)
  supplier = models.ForeignKey(Supplier,
                               on_delete=models.CASCADE,
                               verbose_name='Поставщик',
                               related_name='price_managers',
                               null=True,
                               blank=False)
  has_rrp = models.BooleanField(verbose_name='Есть РРЦ',
                             choices=[(None, 'Без разницы'),(True,'Да'),(False,'Нет')],
                             null=True,
                             blank=True)
  discounts = models.ManyToManyField(Discount,
                               verbose_name='Группа скидок',
                               related_name='price_managers',
                               blank=True)
  source = models.CharField(verbose_name='От какой цены считать',
                                 choices=[
                                  ('rrp', 'РРЦ в валюте поставщика'),
                                  ('supplier_price', 'Цена поставщика в валюте поставщика'),
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
   
MP_TABLE_FIELDS = ['article', 'supplier', 'name', 'manufacturer','prime_cost', 'stock']
MP_CHARS = ['sku', 'article', 'name']
MP_FKS = ['supplier', 'category', 'discount', 'manufacturer', 'price_manager']
MP_DECIMALS = ['weight', 'length', 'width', 'depth']
MP_INTEGERS = ['stock']
MP_PRICES = ['prime_cost', 'wholesale_price', 'basic_price', 'm_price', 'wholesale_price_extra']
MP_MANAGMENT = ['price_updated_at', 'stock_updated_at', 'search_vector']

class MainProduct(models.Model):
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
  price_managers = models.ManyToManyField(
    PriceManager,
    verbose_name='Наценка',
    related_name='main_products',
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
  price_updated_at = models.DateTimeField(verbose_name='Последнее обновление цены',
                                    auto_now_add=True)
  stock_updated_at = models.DateTimeField(verbose_name='Последнее обновление остатка',
                                    auto_now_add=True)
  search_vector = SearchVectorField(null=True, editable=False, unique=False, verbose_name="Вектор поиска")
  def save(self, *args, **kwargs):
    super().save(*args, **kwargs)
    MainProduct.objects.filter(pk=self.pk).update(
        search_vector=SearchVector('name', config='russian')
    )
  def __str__(self):
    return self.sku if self.sku else 'Не указан'
  def _build_search_text(self) -> str:
    """Собираем строку для поиска без join-ов."""
    parts = [
        self.name or "",
        getattr(self.category, "name", "") or "",
        getattr(self.manufacturer, "name", "") or "",
        self.article or "",
        self.sku or "",
    ]
    return " ".join(p for p in parts if p)

  def rebuild_search_vector(self):
    """Обновляет search_vector без join-полей (через константу)."""
    text = self._build_search_text()
    MainProduct.objects.filter(pk=self.pk).update(
        search_vector=SearchVector(Value(text), config='russian')
    )

  def save(self, *args, **kwargs):
      super().save(*args, **kwargs)
      self.rebuild_search_vector()
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
  
SP_TABLE_FIELDS = ['discounts', 'category','article', 'name', 'supplier_price', 'rrp']
SP_CHARS = ['article', 'name']
SP_FKS = ['main_product', 'category', 'supplier', 'manufacturer', 'discounts']
SP_PRICES = ['supplier_price', 'rrp']
SP_INTEGERS = ['stock']
SP_MANAGMENT = ['updated_at']

class SupplierProduct(models.Model):
  main_product=models.ForeignKey(MainProduct,
                        verbose_name='sku',
                        related_name='supplier_product',
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
  priced_only = models.BooleanField(verbose_name='Не включать поля без цены',
                                    default=True)
  update_main = models.BooleanField(verbose_name='Обновлять главный прайс',
                                  default=True)
  differ_by_name = models.BooleanField(verbose_name='Различать по имени',
                                       default=True)
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

# Обработка файлов

class FileModel(models.Model):
  file = models.FileField(verbose_name='Файл',
                         validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm'])],
                         null=False)
  

# Обработка заявок

class AlternateProduct(models.Model):
  name = models.CharField(verbose_name='Название',
                          null=False)
  # filter = models.JSONField(verbose_name='Фильтр',
  #                           null=True)
  main_product = models.ForeignKey(MainProduct, 
                                    verbose_name='Главный продукт',
                                    related_name='alternate_products',
                                    on_delete=models.SET_NULL,
                                    null=True,
                                    blank=True)
  class Meta:
    constraints = [models.UniqueConstraint(fields=['name', 'main_product'], name='name_main_product_constraint')]

class ShopingTab(models.Model):
  user = models.ForeignKey('auth.User',
                           verbose_name='Пользователь',
                           on_delete=models.CASCADE,
                           related_name='shoping_tabs')
  name = models.CharField(verbose_name='Название',
                          null=False)
  products = models.ManyToManyField(AlternateProduct,
                                    verbose_name='Товары',
                                    related_name='shoping_tabs')
  open = models.BooleanField(verbose_name='Открыта',
                             default=True)
  class Meta:
    verbose_name = 'Заявка'
    constraints = [models.UniqueConstraint(fields=['user', 'name'], name='user_name_constraint')]