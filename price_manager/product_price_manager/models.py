from django.db import models
from django.core.validators import (MinValueValidator, MaxValueValidator)
from supplier_manager.models import Supplier, Discount, Category
from supplier_product_manager.models import SupplierProduct, SP_PRICES
from main_product_manager.models import MainProduct, PRICE_TYPES, MP_PRICES, update_logs, MainProductLog
from django.db.models import (F, ExpressionWrapper, 
                              fields, Func, 
                              Value, Min, Max,
                              Q, DecimalField,
                              OuterRef, Subquery, Prefetch,
                              Case, When)
from django.db.models.functions import Ceil
from django.utils import timezone

# Импорты сторонних библиотек
from decimal import Decimal, InvalidOperation


# Модели для применения наценок
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
  class Meta:
    ordering = ['dest', 'source']
  
  name = models.CharField(verbose_name='Название',
                          unique=True)
  supplier = models.ForeignKey(Supplier,
                               on_delete=models.CASCADE,
                               verbose_name='Поставщик',
                               related_name='pricemanagers',
                               null=False,
                               blank=True)
  has_rrp = models.BooleanField(verbose_name='Есть РРЦ',
                             choices=[(None, 'Без разницы'),(True,'Да'),(False,'Нет')],
                             null=True,
                             blank=True)
  discounts = models.ManyToManyField(
    Discount,
    related_name='pricemanagers',
    verbose_name='Группы скидок',
    blank=True
  )
  categories = models.ManyToManyField(
    Category,
    related_name='pricemanagers',
    verbose_name='Категории',
    blank=True
  )
  date_from = models.DateTimeField(
    verbose_name='Дата начала',
    null=True,
    blank=True
  )
  date_to = models.DateTimeField(
    verbose_name='Дата окончания',
    null=True,
    blank=True
  )
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
                                  ('wholesale_price_extra', 'Оптовая цена1'),
                                  ('discount_price', 'Цена со скидкой'),])
  dest = models.CharField(verbose_name='Какую цену считать',
                                 choices=[
                                  (None, 'Не указано'),
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1'),
                                  ('discount_price', 'Цена со скидкой'),],
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
  deprecated = models.BooleanField(
    verbose_name='Устаревший менеджер цен',
    default=False
  )

  def __str__(self):
    return self.name
  
  def get_fitting_mps(self):
    """
    Возвращает продукты подходящие под данный менеджер наценок \\
    Возвращает querryset с аннотацией:\\
    - changed_price - цена после применения наценки\\
      (при подсечете от цен поставщика берет минимальное значение)
    """
    def get_price_querry(price_from, price_to, price_prefix):
      # query = Q(**{f'{price_prefix}__isnull': False})
      # if price_from and price_to:
      #   query &= Q(**{f'{price_prefix}__range':(price_from, price_to)})
      # elif price_from:
      #   query &= Q(**{f'{price_prefix}__gte':price_from})
      # elif price_to:
      #   query &= Q(**{f'{price_prefix}__lte':price_to})
      # return query
      if price_from and price_to:
        return Q(**{f'{price_prefix}__range':(price_from, price_to)})
      elif price_from:
        return Q(**{f'{price_prefix}__gte':price_from})
      elif price_to:
        return Q(**{f'{price_prefix}__lte':price_to})
      else:
        return Q()

    price_manager = self
    mps = MainProduct.objects.all().prefetch_related('supplierproducts')
    products = SupplierProduct.objects.all().prefetch_related('main_product')
    products = products.filter(
      supplier=price_manager.supplier)
    if not price_manager.has_rrp is None:
      if price_manager.has_rrp:
        products = products.filter(rrp__gt=0)
      else:
        products = products.filter(Q(rrp=0)|Q(rrp__isnull=True))


    if price_manager.source in SP_PRICES:
      products = products.filter(get_price_querry(
        price_manager.price_from,
        price_manager.price_to,
        price_manager.source))
      if price_manager.discounts.exists():
        products = products.filter(discount__in=price_manager.discounts.all())
    elif price_manager.source in MP_PRICES:
      products = products.filter(get_price_querry(
        price_manager.price_from,
        price_manager.price_to,
        f'''main_product__{price_manager.source}'''))
    
    mps = MainProduct.objects.filter(pk__in=products.values_list('main_product', flat=True))
    if price_manager.categories.exists():
      mps = mps.filter(category__in=price_manager.categories.all())
    source = price_manager.source
    if price_manager.source in SP_PRICES:
      mps = mps.annotate(source_price=Min(f'supplierproducts__{price_manager.source}'))
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
    elif price_manager.source in MP_PRICES:
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
    else:
      calc_qs = (
        mps.filter(pk=OuterRef("pk"))
        .annotate(
            _changed_price=ExpressionWrapper(
                Ceil(
                  Decimal(price_manager.fixed_price)
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
  
  def update_pricetags(self):
    pts = self.pricetags.values_list('mp', flat=True)
    mps = self.get_fitting_mps().filter(~Q(pk__in=pts))
    pts = map(
      lambda item: 
        PriceTag(**{
          'mp':item[1],
          'p_manager':item[0],
          'source':item[0].source,
          'dest':item[0].dest,
          'markup':item[0].markup,
          'increase':item[0].increase,
          'fixed_price':item[0].fixed_price
        }), zip([self]*mps.count(), mps))
    return PriceTag.objects.bulk_create(
      pts, 
      update_conflicts=True, 
      unique_fields=['mp', 'p_manager', 'dest'], 
      update_fields=[
        'source',
        'markup',
        'increase',
        'fixed_price'])
  
  def save(self, **kwargs):
    super().save(**kwargs)
    if self.deprecated: return None
    mps = self.get_fitting_mps()
    pts = map(
      lambda item: 
        PriceTag(**{
          'mp':item[1],
          'p_manager':item[0],
          'source':item[0].source,
          'dest':item[0].dest,
          'markup':item[0].markup,
          'increase':item[0].increase,
          'fixed_price':item[0].fixed_price
        }), zip([self]*mps.count(), mps))
    PriceTag.objects.bulk_create(
      pts, 
      update_conflicts=True, 
      unique_fields=['mp', 'p_manager', 'dest'], 
      update_fields=[
        'source',
        'markup',
        'increase',
        'fixed_price'])

  def apply(self):
    mps = self.get_fitting_mps()
    mps = mps.filter(~Q(**{self.dest: F('changed_price')}))
    mpls = map(lambda mp: MainProductLog(price_type=self.dest, main_product=mp, price=getattr(mp, 'changed_price')), mps)
    MainProductLog.objects.bulk_create(mpls)
    self.update_pricetags()
    if mps.exists():
      print('\n\n\n', self.supplier, ': ', self.source, ',', self.dest, ';', self.price_from, ',', self.price_to)
      print('Группы скидок', self.discounts.all())
      print('Категории', self.categories.all())
      print(mps)
    return mps.update(**{self.dest:F('changed_price')})

  def delete(self, *args, **kwargs):
    mps = self.get_fitting_mps()
    setattr(mps, self.dest, Value(None))
    MainProduct.objects.bulk_update(mps, fields=[self.dest, 'price_updated_at'])
    super().delete(*args, **kwargs)

  def deprecate(self):
    mps = self.get_fitting_mps()
    self.pricetags.all().delete()
    self.deprecated = True
    self.save()
    return mps.update(**{self.dest:Value(None)})



class PriceTag(models.Model):
  class Meta:
    verbose_name = ("Наценка")
    verbose_name_plural = ("Наценки")
    constraints = [models.UniqueConstraint(fields=['mp', 'p_manager', 'dest'], name='pricetag_constraint')]
  mp = models.ForeignKey(verbose_name="Товар главного прайса",
                                to=MainProduct,
                                related_name='pricetags',
                                on_delete=models.CASCADE)
  p_manager = models.ForeignKey(verbose_name="Менеджер наценок",
                                to=PriceManager,
                                related_name='pricetags',
                                on_delete=models.CASCADE,
                                null=True)
  date_from = models.DateTimeField(
    verbose_name='Дата начала',
    null=True,
    blank=True
  )
  date_to = models.DateTimeField(
    verbose_name='Дата окончания',
    null=True,
    blank=True
  )
  source = models.CharField(verbose_name='От какой цены считать',
                                 choices=[
                                  (None, 'Фиксированная цена'),
                                  ('rrp', 'РРЦ в валюте поставщика'),
                                  ('supplier_price', 'Цена поставщика в валюте поставщика'),
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1'),
                                  ('discount_price', 'Цена со скидкой'),],
                                  blank=True,
                                  null=True)
  dest = models.CharField(verbose_name='Какую цену считать',
                                 choices=[
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1'),
                                  ('discount_price', 'Цена со скидкой'),],
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
      verbose_name='Фиксированная цена (тг)',
      decimal_places=2,
      max_digits=20,
      validators=[MinValueValidator(0)],
      null=True,
      blank=True)
  deprecated = models.BooleanField(
    verbose_name='Устаревшая наценка',
    default=False
  )
  def __str__(self):
    if self.source:
      return f'{PRICE_TYPES[self.source]} -> {PRICE_TYPES[self.dest]} ({(1+self.markup/100)*100}% + {self.increase} тг.)'
    else:
      return f'{PRICE_TYPES[self.dest]}: {self.fixed_price}'
  
  def get_aggfunc():
    '''
    Функция для аггрегации цен поставщика
    '''
    return max

  def get_sprice(self):
    if self.source == 'fixed_price':
      return self.fixed_price
    if self.source in MP_PRICES:
      return self.get_aggfunc()(
        self.mp.supplierproducts.filter(**{f'{self.source}__isnull':False}).values_list(self.source, flat=True) 
        ) * self.mp.supplier.currency.value()
    return getattr(self.mp, self.source)
  
  def get_dprice(self):
    return self.get_sprice()*(1+self.markup/100) + self.increase

  def get_mp(self):
    mp = self.mp
    new_price = self.get_dprice()
    if not getattr(mp, self.dest) == new_price:
      setattr(mp, self.dest, new_price)
    MainProductLog.objects.create(price_type=self.dest, main_product=mp, price=getattr(mp, self.dest))
    return mp
  
  def delete(self, *args, **kwargs):
    setattr(self.mp, self.dest, None)
    self.mp.save()
    super().delete(*args, **kwargs)

  def deprecate(self):
    if self.deprecated: return None
    mp = self.mp
    if not getattr(mp, self.dest): return None
    setattr(mp, self.dest, None)
    self.deprecated=True
    self.save()
    return mp


def update_prices():
  count = 0
  dcount = 0
  
  pms = PriceManager.objects.filter(deprecated=False)
  now = timezone.now()
  time_query = (Q(date_from__lt=now)|Q(date_from__isnull=True))&(Q(date_to__gt=now)|Q(date_to__isnull=True))
  for pm in pms.filter(~Q(time_query)).all():
    dcount += pm.deprecate()
  for pm in pms.filter(time_query).filter(source__in=SP_PRICES):
    count += pm.apply()
  for pm in pms.filter(time_query).filter(source__in=MP_PRICES):
    count += pm.apply()
  dmps = map(lambda pt: pt.deprecate(),PriceTag.objects.filter(p_manager__isnull=True).filter(~Q(time_query)).select_related('mp'))
  dcount += MainProduct.objects.bulk_update([_ for _ in dmps if _], fields=[*MP_PRICES, 'price_updated_at'])
  mps = map(lambda pt: pt.get_mp(),PriceTag.objects.filter(p_manager__isnull=True).filter(time_query).filter(source__in=SP_PRICES).select_related('mp'))
  count += MainProduct.objects.bulk_update(mps, fields=[*MP_PRICES, 'price_updated_at'])
  mps = map(lambda pt: pt.get_mp(),PriceTag.objects.filter(p_manager__isnull=True).filter(time_query).filter(source__in=MP_PRICES).select_related('mp'))
  count += MainProduct.objects.bulk_update(mps, fields=[*MP_PRICES, 'price_updated_at'])

  return (count, dcount)