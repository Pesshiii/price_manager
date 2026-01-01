from django.db import models
from django.contrib.postgres.search import SearchVectorField, SearchVector 
from django.contrib.postgres.indexes import GinIndex
from django.db.models import Value, OuterRef, Subquery, Q, F
from django.core.validators import MinValueValidator, MaxValueValidator
from supplier_manager.models import Supplier, Category, Manufacturer

   
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
        name='mp_unique_supplier_article_name'
      )
    ]
    indexes = [
      GinIndex(fields=['search_vector']),
    ]

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
    constraints = [
      models.UniqueConstraint(
        fields=['update_time', 'main_product'],
        name='mpl_unique_date_mp'
      )
    ]


def update_logs():
  updated_logs = 0
  for price_type in MP_PRICES[1:]:
    latest_log_subquery = MainProductLog.filter(
      main_product__pk=OuterRef('pk')
    ).filter(price_type=price_type).order_by('-update_time').values(['update_time', 'price'])[:1]

    mps = MainProduct.objects.annotate(
      latest_log_update=Subquery(latest_log_subquery['update_time']),
      latest_log_price=Subquery(latest_log_subquery['price'])
    )
    mps = mps.filter(~Q(**{price_type:'latest_log_price'}))
    updated_logs += mps.update(**{price_type:'latest_log_price'})
  latest_log_subquery = MainProductLog.filter(
      main_product__pk=OuterRef('pk')
    ).filter(price_type=price_type).order_by('-update_time').values(['update_time', 'stock'])[:1]

  mps = MainProduct.objects.annotate(
    latest_log_update=Subquery(latest_log_subquery['update_time']),
    latest_log_stock=Subquery(latest_log_subquery['stock'])
  )
  mps = mps.filter(~Q(**{'stock':'latest_log_stock'}))
  updated_logs += mps.update(**{'stock':'latest_log_stock'})
  return updated_logs