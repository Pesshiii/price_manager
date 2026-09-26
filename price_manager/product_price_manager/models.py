from django.db import models
from django.core.validators import (MinValueValidator, MaxValueValidator)
from supplier_manager.models import Supplier, Discount
from supplier_product_manager.models import SupplierProduct, SP_PRICES
from main_product_manager.models import MainProduct, PRICE_TYPES, MP_PRICES, MainProductLog
from django.db.models import (F, ExpressionWrapper, 
                              fields, Func, 
                              Value, Min, Max,
                              Q, DecimalField,
                              OuterRef, Subquery, Prefetch,
                              Case, When, Exists)
from django.db.models.functions import Ceil, Coalesce, NullIf
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
  # Пусто — правило на строки ГП без поставщика: наборы, возвраты, бонусы,
  # остатки на складе (_fitting_unsupplied_mps).
  supplier = models.ForeignKey(Supplier,
                               on_delete=models.CASCADE,
                               verbose_name='Поставщик',
                               related_name='pricemanagers',
                               null=True,
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
                                  ('kaspi_price', 'Цена Каспи'),
                                  ('discount_price', 'Цена со скидкой'),])
  dest = models.CharField(verbose_name='Какую цену считать',
                                 choices=[
                                  (None, 'Не указано'),
                                  ('basic_price', 'Базовая цена'),
                                  ('prime_cost', 'Себестоимость'),
                                  ('m_price', 'Цена ИМ'),
                                  ('wholesale_price', 'Оптовая цена'),
                                  ('wholesale_price_extra', 'Оптовая цена1'),
                                  ('kaspi_price', 'Цена Каспи'),
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
      validators=[MinValueValidator(-100)],
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
      (при подсчете от цен поставщика берет последнюю строку
      SupplierProduct по updated_at; строка всегда ровно одна —
      SupplierProduct.main_product объявлен unique=True)
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
    if price_manager.supplier_id is None:
      return price_manager._fitting_unsupplied_mps(get_price_querry)
    products = SupplierProduct.objects.filter(
      supplier=price_manager.supplier
    ).prefetch_related('main_product')
    if not price_manager.has_rrp is None:
      if price_manager.has_rrp:
        products = products.filter(rrp__gt=0)
      else:
        products = products.filter(Q(rrp=0)|Q(rrp__isnull=True))
    if price_manager.discounts.exists():
      products = products.filter(discount__in=price_manager.discounts.all())


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
    
    mps = MainProduct.objects.filter(pk__in=products.values_list('main_product', flat=True))
    source = price_manager.source
    if price_manager.source in SP_PRICES:
      filtered_source_price = (
        products.filter(main_product=OuterRef('pk'))
        .order_by('-updated_at')
        .values(price_manager.source)[:1]
      )
      # An empty (NULL) or 0 supplier price is "no price": it yields a NULL
      # changed_price, which apply() skips and clear_unsourced_prices() turns
      # into a NULL dest. It used to be coalesced to 0, which priced the
      # product at the rule's bare `increase`.
      mps = mps.annotate(
        source_price=NullIf(
          Subquery(filtered_source_price, output_field=DecimalField()),
          Value(Decimal('0')),
          output_field=DecimalField()
        )
      )
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
                    NullIf(F(source), Value(Decimal('0')))
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

  def _fitting_unsupplied_mps(self, get_price_querry):
    """get_fitting_mps правила без поставщика: строки ГП без поставщика.

    Это возвраты, бонусы, остатки и строки наборов. Прайса поставщика у них
    нет, поэтому РРЦ, группы скидок и источники из ПП к ним неприменимы:
    правило с таким источником не подходит ни одной строке, а не считает от
    пустого. Себестоимость строки набора — сумма комплектующих
    (product.services.set_rows), правило её не пишет. Остальное — как у
    правила поставщика: диапазон цены-источника, формула.
    """
    mps = MainProduct.objects.filter(supplier__isnull=True)
    if self.source in SP_PRICES:
      return mps.none().annotate(changed_price=Value(None, output_field=DecimalField()))
    if self.dest == 'prime_cost':
      mps = mps.filter(is_set=False)
    if self.source in MP_PRICES:
      mps = mps.filter(get_price_querry(self.price_from, self.price_to, self.source))
    if self.source in MP_PRICES:
      changed = Ceil(NullIf(F(self.source), Value(Decimal('0')))
                     * (1 + Decimal(self.markup) / Decimal(100)) + Decimal(self.increase))
    else:
      changed = Ceil(Value(Decimal(self.fixed_price)))
    calc_qs = (mps.filter(pk=OuterRef('pk'))
               .annotate(_changed_price=ExpressionWrapper(changed, output_field=DecimalField()))
               .values('_changed_price')[:1])
    return mps.annotate(changed_price=Subquery(calc_qs, output_field=DecimalField()))

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

  def apply(self, logs: bool = True):
    mps = self.get_fitting_mps()
    # A rule only ever writes a real price. Products without a source price get
    # a NULL changed_price and are cleared by clear_unsourced_prices() instead:
    # comparing a dest against NULL in the filter below is not a reliable way
    # to select them.
    mps = mps.filter(changed_price__isnull=False)
    mps = mps.filter(~Q(**{self.dest: F('changed_price')}))
    if logs:
        mpls = map(lambda mp: MainProductLog(price_type=self.dest, main_product=mp, price=getattr(mp, 'changed_price')), mps)
        MainProductLog.objects.bulk_create(mpls)
    self.update_pricetags()
    if mps.exists():
      print('\n\n\n', self.supplier, ': ', self.source, ',', self.dest, ';', self.price_from, ',', self.price_to)
      print('Группы скидок', self.discounts.all())
      print(mps)
    return mps.update(**{self.dest:F('changed_price'), 'price_updated_at':timezone.now()})

  def delete(self, *args, **kwargs):
    mps = self.get_fitting_mps()
    mps.update(**{self.dest:None, 'price_updated_at':timezone.now()})
    super().delete(*args, **kwargs)

  def deprecate(self):
    mps = self.get_fitting_mps()
    self.pricetags.all().delete()
    self.deprecated = True
    self.save(update_fields=['deprecated'])
    return mps.update(**{self.dest:None, 'price_updated_at':timezone.now()})



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
                                  ('kaspi_price', 'Цена Каспи'),
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
                                    ('kaspi_price', 'Цена Каспи'),
                                    ('discount_price', 'Цена со скидкой'),],
                                  blank=True,
                                  null=True)
  markup = models.DecimalField(
      verbose_name='Накрутка',
      decimal_places=2,
      max_digits=5,
      validators=[MinValueValidator(-100)],
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
  
  def get_sprice(self):
    if self.source in ('fixed_price', None):
      return self.fixed_price
    if self.source in SP_PRICES:
      sp = self.mp.supplierproducts.order_by('-updated_at').first()
      price = getattr(sp, self.source) if sp is not None else None
      # NULL or 0 is "no price" — see clear_unsourced_prices().
      return price * self.mp.supplier.currency.value if price else None
    if self.source in MP_PRICES:
      return getattr(self.mp, self.source) or None
    return None
  
  def get_dprice(self):
    source_price = self.get_sprice()
    if source_price is None:
      return None
    return source_price*(1+self.markup/100) + self.increase

  def get_mp(self):
    mp = self.mp
    new_price = self.get_dprice()
    if new_price is None:
      return None
    if not getattr(mp, self.dest) == new_price:
      setattr(mp, self.dest, new_price)
      mp.price_updated_at = timezone.now()
      MainProductLog.objects.create(price_type=self.dest, main_product=mp, price=getattr(mp, self.dest))
      return mp
    return None
  
  def delete(self, *args, **kwargs):
    setattr(self.mp, self.dest, None)
    self.mp.price_updated_at = timezone.now()
    self.mp.save()
    super().delete(*args, **kwargs)

  def deprecate(self):
    if self.deprecated: return None
    mp = self.mp
    if not getattr(mp, self.dest): return None
    setattr(mp, self.dest, None)
    mp.price_updated_at = timezone.now()
    self.deprecated=True
    self.save()
    return mp


def _active_pricetags(now):
  """PriceTag, которые сейчас действуют: живого правила в его сроке или ручные в своём."""
  def window(prefix=''):
    return ((Q(**{f'{prefix}date_from__lt': now}) | Q(**{f'{prefix}date_from__isnull': True}))
            & (Q(**{f'{prefix}date_to__gt': now}) | Q(**{f'{prefix}date_to__isnull': True})))
  from_rule = Q(p_manager__isnull=False, p_manager__deprecated=False) & window('p_manager__')
  manual = Q(p_manager__isnull=True, deprecated=False) & window()
  return PriceTag.objects.filter(from_rule | manual)


def _clearing_candidates(tags, dest) -> set:
  """Товары с заполненной dest и хотя бы одной наценкой на неё с пустым источником.

  Дешёвый предварительный отбор простыми join'ами: точная проверка в
  clear_unsourced_prices с подзапросами по каждой наценке иначе проходила бы
  по всему каталогу на каждом update_prices, хотя в обычном прогоне очищать
  нечего. Проверки «последней строки поставщика» здесь нет — у MainProduct
  не больше одного SupplierProduct (unique FK), а лишний кандидат всё равно
  отсеет точная проверка.
  """
  dest_tags = tags.filter(dest=dest, **{f'mp__{dest}__isnull': False})
  empty = Q()
  for source in SP_PRICES:
    empty |= Q(source=source) & (Q(**{f'mp__supplierproducts__{source}__isnull': True})
                                 | Q(**{f'mp__supplierproducts__{source}': 0}))
  for source in MP_PRICES:
    empty |= Q(source=source) & (Q(**{f'mp__{source}__isnull': True}) | Q(**{f'mp__{source}': 0}))
  return set(dest_tags.filter(empty).values_list('mp_id', flat=True))


def clear_unsourced_prices(logs: bool = True, now=None) -> int:
  """Очистить цены ГП, которым не от чего считаться.

  Цена dest товара очищается (NULL), когда у него есть действующая наценка на
  эту dest и у **каждой** такой наценки источник пуст: цена поставщика (по
  последней строке поставщика) или цена ГП равна NULL или 0. Наценка с
  фиксированной ценой или с непустым источником цену сохраняет — её выставит
  сама наценка.

  Без этого шага пустой источник давал либо цену, равную надбавке правила
  (было Coalesce(источник, 0)), либо навсегда застывшую старую цену — у
  правила с диапазоном цен товар из правила просто выпадал.

  Проходит повторно, пока есть что очищать: очищенная базовая цена делает
  пустым источник цен, посчитанных от неё. Возвращает число очищенных цен.
  """
  now = now or timezone.now()
  tags = _active_pricetags(now)
  cleared_total = 0
  # A clearing pass can only empty more sources, never refill one, so the
  # cascade settles within one pass per price field.
  for _ in range(len(MP_PRICES)):
    cleared = 0
    for dest in MP_PRICES:
      candidates = _clearing_candidates(tags, dest)
      if not candidates:
        continue
      dest_tags = tags.filter(mp=OuterRef('pk'), dest=dest)
      mps = (MainProduct.objects
             .filter(pk__in=candidates, **{f'{dest}__isnull': False})
             .filter(Exists(dest_tags))
             .exclude(Exists(dest_tags.filter(Q(source__isnull=True) | Q(source='fixed_price')))))
      for source in SP_PRICES:
        latest = (SupplierProduct.objects.filter(main_product=OuterRef('pk'))
                  .order_by('-updated_at').values(source)[:1])
        mps = mps.annotate(**{
          f'_has_{source}': Exists(dest_tags.filter(source=source)),
          f'_src_{source}': NullIf(Subquery(latest, output_field=DecimalField()),
                                   Value(Decimal('0')), output_field=DecimalField()),
        }).exclude(**{f'_has_{source}': True, f'_src_{source}__isnull': False})
      for source in MP_PRICES:
        mps = mps.annotate(**{f'_has_{source}': Exists(dest_tags.filter(source=source))}
                           ).exclude(**{f'_has_{source}': True, f'{source}__gt': 0})
      ids = list(mps.values_list('pk', flat=True))
      if not ids:
        continue
      if logs:
        MainProductLog.objects.bulk_create(
          MainProductLog(price_type=dest, main_product_id=pk, price=None) for pk in ids)
      cleared += MainProduct.objects.filter(pk__in=ids).update(**{dest: None, 'price_updated_at': now})
    if not cleared:
      break
    cleared_total += cleared
  return cleared_total


def update_prices(logs: bool = True):
  def get_updated_mps(pricetags):
    updated_mps = {}
    for pt in pricetags.select_related('mp'):
      updated_mp = pt.get_mp()
      if not updated_mp:
        continue
      if updated_mp.pk not in updated_mps:
        updated_mps[updated_mp.pk] = updated_mp
        continue
      target_mp = updated_mps[updated_mp.pk]
      setattr(target_mp, pt.dest, getattr(updated_mp, pt.dest))
      target_mp.price_updated_at = updated_mp.price_updated_at
    return list(updated_mps.values())

  count = 0
  dcount = 0
  
  pms = PriceManager.objects.filter(deprecated=False)
  now = timezone.now()
  time_query = (Q(date_from__lt=now)|Q(date_from__isnull=True))&(Q(date_to__gt=now)|Q(date_to__isnull=True))
  for pm in pms.filter(~Q(time_query)).all():
    dcount += pm.deprecate()
  for pm in pms.filter(time_query).filter(source__in=SP_PRICES):
    count += pm.apply(logs=logs)
  for pm in pms.filter(time_query).filter(source__in=MP_PRICES):
    count += pm.apply(logs=logs)
  for pm in pms.filter(time_query).filter(source='fixed_price'):
    count += pm.apply(logs=logs)
  dmps = map(lambda pt: pt.deprecate(),PriceTag.objects.filter(p_manager__isnull=True).filter(~Q(time_query)).select_related('mp'))
  deprecated_mps = [_ for _ in dmps if _]
  if deprecated_mps:
    dcount += MainProduct.objects.bulk_update(deprecated_mps, fields=[*MP_PRICES, 'price_updated_at'])
  sp_mps = get_updated_mps(
    PriceTag.objects.filter(p_manager__isnull=True).filter(time_query).filter(source__in=SP_PRICES)
  )
  if sp_mps:
    count += MainProduct.objects.bulk_update(sp_mps, fields=[*MP_PRICES, 'price_updated_at'])
  mp_mps = get_updated_mps(
    PriceTag.objects.filter(p_manager__isnull=True).filter(time_query).filter(source__in=MP_PRICES)
  )
  if mp_mps:
    count += MainProduct.objects.bulk_update(mp_mps, fields=[*MP_PRICES, 'price_updated_at'])
  fixed_mps = get_updated_mps(
    PriceTag.objects.filter(p_manager__isnull=True).filter(time_query).filter(Q(source='fixed_price')|Q(source__isnull=True))
  )
  if fixed_mps:
    count += MainProduct.objects.bulk_update(fixed_mps, fields=[*MP_PRICES, 'price_updated_at'])

  # Наборы — последними. Себестоимость строки набора — сумма себестоимостей
  # комплектующих, и те только что пересчитали наценки выше; потом по новой
  # себестоимости ещё раз проходят наценки без поставщика и ручные наценки
  # строк наборов — только их, остальным строкам пересчитывать нечего.
  from product.services.set_rows import sync_set_rows
  count += sync_set_rows(logs=logs)['updated']
  for pm in pms.filter(time_query).filter(supplier__isnull=True).exclude(source__in=SP_PRICES):
    count += pm.apply(logs=logs)
  set_tags = PriceTag.objects.filter(p_manager__isnull=True, mp__is_set=True).filter(time_query)
  set_mps = get_updated_mps(set_tags.filter(source__in=MP_PRICES))
  if set_mps:
    count += MainProduct.objects.bulk_update(set_mps, fields=[*MP_PRICES, 'price_updated_at'])

  # Last, after every rule and tag had its chance to write a real price.
  dcount += clear_unsourced_prices(logs=logs, now=now)

  return (count, dcount)
