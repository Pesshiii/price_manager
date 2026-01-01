from django.db import models
from django.core.validators import (MinValueValidator, MaxValueValidator)
from supplier_manager.models import Supplier
from supplier_product_manager.models import SupplierProduct, SP_PRICES
from main_product_manager.models import MainProduct, MP_PRICES
from django.db.models import (F, ExpressionWrapper, 
                              fields, Func, 
                              Value, Min,
                              Q, DecimalField,
                              OuterRef, Subquery)
from django.db.models.functions import Ceil


# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation


# Модели для применения наценок

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
}

class PriceManager(models.Model):
  """
  Модель PriceManager предназначена для управления ценами и скидками товаров от различных поставщиков.
  Атрибуты:
    name (CharField): Название менеджера цен. Должно быть уникальным.
    supplier (ForeignKey): Ссылка на поставщика (Supplier). При удалении поставщика связанные менеджеры цен также удаляются.
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
                               null=False,
                               blank=True)
  has_rrp = models.BooleanField(verbose_name='Есть РРЦ',
                             choices=[(None, 'Без разницы'),(True,'Да'),(False,'Нет')],
                             null=True,
                             blank=True)
  source = models.CharField(verbose_name='От какой цены считать',
                                 choices=[
                                  (None, 'Не указано'),
                                  ('fixed_price', 'Фиксированная цена'),
                                  ('rrp', 'РРЦ в валюте поставщика'),
                                  ('supplier_price', 'Цена поставщика в валюте поставщика'),
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1')])
  dest = models.CharField(verbose_name='Какую цену считать',
                                 choices=[
                                  (None, 'Не указано'),
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1')],
                                  blank=False)
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
  fixed_price = models.DecimalField(
      verbose_name='Значение фиксированной цены',
      decimal_places=2,
      max_digits=20,
      validators=[MinValueValidator(0)],
      default=0)
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
  def get_fitting_mps(self):
    """
    Возвращает продукты подходящие под данный менеджер наценок \\
    Возвращает querryset с аннотацией:\\
    - changed_price - цена после применения наценки
    """
    def get_price_querry(price_from, price_to, price_prefix):
      if price_from and price_to:
        return Q(**{f'{price_prefix}__range':(price_from, price_to)})
      elif price_from:
        return Q(**{f'{price_prefix}__gte':price_from})
      elif price_to:
        return Q(**{f'{price_prefix}__lte':price_to})
      else:
        return Q()
    price_manager = self
    mps = MainProduct.objects.all().prefetch_related('supplier_products')
    products = SupplierProduct.objects.all()
    products = products.filter(
      supplier=price_manager.supplier)
    if not price_manager.has_rrp is None:
      if price_manager.has_rrp:
        products = products.filter(rrp__gt=0)
      else:
        products = products.filter(rrp=0)


    if price_manager.source in SP_PRICES:
      products = products.filter(get_price_querry(
        price_manager.price_from,
        price_manager.price_to,
        price_manager.source))
    elif price_manager.source in MP_PRICES:
      products = products.filter(get_price_querry(
        price_manager.price_from,
        price_manager.price_to,
        f'''main_product__{price_manager.source}'''))
    
    mps = MainProduct.objects.filter(id__in=products.values_list('main_product__id'))
    source = price_manager.source
    if price_manager.source in SP_PRICES:
      mps = mps.annotate(source_price=Min(f'supplier_products__{price_manager.source}'))
      source = 'source_price'
      calc_qs = (
        mps.filter(pk=OuterRef("pk"))
        .annotate(
            _changed_price=ExpressionWrapper(
                Ceil(
                    F(source) * F("supplier__currency__value")
                    * (1 + Decimal(price_manager.markup) / Decimal(100))
                    + Decimal(price_manager.increase)
                ),
                output_field=DecimalField(),
            )
        )
        .values("_changed_price")[:1]
      )
    else:
      calc_qs = (
        mps.filter(pk=OuterRef("pk"))
        .annotate(
            _changed_price=ExpressionWrapper(
                Ceil(
                    F(source)
                    * (1 + Decimal(price_manager.markup) / Decimal(100))
                    + Decimal(price_manager.increase)
                ),
                output_field=DecimalField(),
            )
        )
        .values("_changed_price")[:1]
      )
    
    mps = mps.annotate(
          changed_price=Subquery(calc_qs, output_field=DecimalField())
      )
    
    return mps

    

class SpecialPrice(models.Model):
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
  source = models.CharField(verbose_name='От какой цены считать',
                                 choices=[
                                  (None, 'Фиксированная цена'),
                                  ('rrp', 'РРЦ в валюте поставщика'),
                                  ('supplier_price', 'Цена поставщика в валюте поставщика'),
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1')],
                                  blank=True,
                                  null=True)
  dest = models.CharField(verbose_name='Какую цену считать',
                                 choices=[
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1')],
                                  blank=True,
                                  null=True)
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
  fixed_price = models.DecimalField(
      verbose_name='Фиксированная цена',
      decimal_places=2,
      max_digits=20,
      validators=[MinValueValidator(0)],
      null=True,
      blank=True)
  def __str__(self):
    if self.source:
      return f'{PRICE_TYPES[self.source]} -> {PRICE_TYPES[self.dest]} ({(1+self.markup/100)*100}% + {self.increase} тг.)'
    else:
      return f'{PRICE_TYPES[self.dest]}: {self.fixed_price}'


class PriceTag(models.Model):
  mp = models.ForeignKey(verbose_name="Товар главного прайса",
                                to=MainProduct,
                                related_name='pricetags',
                                on_delete=models.CASCADE)
  p_manager = models.ForeignKey(verbose_name="Менеджер наценок",
                                to=PriceManager,
                                related_name='pricetags',
                                on_delete=models.CASCADE)
  source = models.CharField(verbose_name='От какой цены считать',
                                 choices=[
                                  (None, 'Фиксированная цена'),
                                  ('rrp', 'РРЦ в валюте поставщика'),
                                  ('supplier_price', 'Цена поставщика в валюте поставщика'),
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1')],
                                  blank=True,
                                  null=True)
  dest = models.CharField(verbose_name='Какую цену считать',
                                 choices=[
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1')],
                                  blank=True,
                                  null=True)
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
  fixed_price = models.DecimalField(
      verbose_name='Фиксированная цена',
      decimal_places=2,
      max_digits=20,
      validators=[MinValueValidator(0)],
      null=True,
      blank=True)
  def __str__(self):
    if self.source:
      return f'{PRICE_TYPES[self.source]} -> {PRICE_TYPES[self.dest]} ({(1+self.markup/100)*100}% + {self.increase} тг.)'
    else:
      return f'{PRICE_TYPES[self.dest]}: {self.fixed_price}'


  class Meta:
    verbose_name = ("Наценка")
    verbose_name_plural = ("Наценки")

  def __str__(self):
    return self.name
  

def update_pricetags():
  for pm in PriceManager.objects.all().prefetch_related('pricetags'):
    pts = pm.pricetags.values('mp')[:1]['mp']
    mps = pm.get_fitting_mps().filter(~Q(pricetags__in=pts))
    for mp in mps:
      pt = PriceTag.objects.get_or_create(
        defaults={
          'mp':mp,
          'p_manager':pm,
          'source':pm.source,
          'dest':pm.dest,
          'markup':pm.markup,
          'increase':pm.increase,
          'fixed_price':pm.fixed_price
        }
        )[0]
      pt.save()



def update_prices():
  mps = MainProduct.objects.all().prefetch_related('supplier_products', 'pricetags')
  