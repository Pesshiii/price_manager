from django.db import models
from django.core.validators import (MinValueValidator, MaxValueValidator)
from supplier_manager.models import Supplier, Discount
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


class UniquePriceManager(models.Model):
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