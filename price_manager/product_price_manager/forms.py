from django import forms
from supplier_manager.models import Discount, Supplier
from supplier_product_manager.models import SP_PRICES
from .models import PriceManager, PriceTag


RULE_SOURCE_CHOICES = (
  (None, 'Не указано'),
  ('rrp', 'РРЦ в валюте поставщика'),
  ('supplier_price', 'Цена поставщика в валюте поставщика'),
  ('basic_price', 'Базовая цена'),
  ('prime_cost', 'Себестоимость'),
  ('m_price', 'Цена ИМ'),
  ('wholesale_price', 'Оптовая цена'),
  ('wholesale_price_extra', 'Оптовая цена1'))

# Поля, при смене которых форма правила перерисовывается: от них зависят
# допустимые группы скидок, источники и единица диапазона цены.
RULE_REFRESH_FIELDS = ('supplier', 'source', 'dest')


class PriceManagerForm(forms.ModelForm):
  """Форма правила наценки ГП.

  Поставщик — поле самой формы: от него зависят группы скидок, РРЦ и
  источники из прайса. Выборы сужаются в __init__, до валидации, под
  поставщика из присланных данных (или из initial/instance, если форма не
  связана), поэтому группа скидок чужого поставщика не проходит is_valid().
  У существующего правила поставщик заблокирован (lock_supplier): save()
  не убирает ценники строк, выпавших из правила, и смена поставщика
  оставила бы им цены старого.
  """
  name = forms.CharField(
    label='Название',
    required=False,
    help_text='Будет сгенерировано автоматически при сохранении на основе выбранных настроек.'
  )
  supplier = forms.ModelChoiceField(
    queryset=Supplier.objects.none(),
    label='Поставщик',
    required=False,
    empty_label='Без поставщика — наборы, возвраты, бонусы, остатки',
  )
  price_fixed = forms.BooleanField(widget=forms.widgets.CheckboxInput(), label='Фиксированная цена', required=False)
  source = forms.CharField(widget=forms.widgets.Select(choices=RULE_SOURCE_CHOICES),
    label="От какой цены считать",
    required=False)
  class Meta:
    model = PriceManager
    fields = (
      'name', 'supplier',
      'has_rrp', 'discounts',
      'date_from', 'date_to',
      'price_from', 'price_to',
      'source', 'dest',
      'price_fixed', 'fixed_price',
      'markup', 'increase',
    )

  def __init__(self, *args, lock_supplier=False, **kwargs):
    super().__init__(*args, **kwargs)
    self.fields['supplier'].queryset = Supplier.objects.select_related('currency').order_by('name')
    self.fields['supplier'].disabled = lock_supplier
    self.rule_supplier = self._current_supplier()
    supplier = self.rule_supplier
    self.fields['discounts'].queryset = supplier.discounts.all() if supplier else Discount.objects.none()
    # Источник не может совпадать с тем, что считаем, а у строк без
    # поставщика нет прайса поставщика. Это подсказка в выборе; настоящая
    # проверка — views._rule_error и PriceManager.clean().
    dest = self._current_value('dest')
    self.fields['source'].widget.choices = [
      (value, label) for value, label in RULE_SOURCE_CHOICES
      if not (value and value == dest) and not (supplier is None and value in SP_PRICES)]
    for name in RULE_REFRESH_FIELDS:
      self.fields[name].widget.attrs['data-rule-refresh'] = ''

  def _current_value(self, name):
    if self.is_bound and not self.fields[name].disabled:
      return self.data.get(self.add_prefix(name)) or None
    value = self.get_initial_for_field(self.fields[name], name)
    return getattr(value, 'pk', value)

  def _current_supplier(self):
    pk = self._current_value('supplier')
    if pk in (None, '') or not str(pk).isdigit():
      return None
    return self.fields['supplier'].queryset.filter(pk=pk).first()

  @property
  def range_unit(self):
    """Единица диапазона цены: от цены из прайса — валюта поставщика
    (get_fitting_mps сравнивает её без пересчёта), иначе тенге."""
    supplier = self.rule_supplier
    if supplier and supplier.currency and self._current_value('source') in SP_PRICES:
      return supplier.currency.name
    return 'тг'

  def selected_discount_ids(self):
    """Отмеченные группы скидок — только из допустимых для поставщика."""
    if self.is_bound and hasattr(self.data, 'getlist'):
      raw = self.data.getlist(self.add_prefix('discounts'))
    elif self.is_bound:
      raw = self.data.get(self.add_prefix('discounts')) or []
    else:
      raw = self.get_initial_for_field(self.fields['discounts'], 'discounts') or []
    ids = {str(getattr(value, 'pk', value)) for value in raw}
    return [pk for pk in self.fields['discounts'].queryset.values_list('pk', flat=True) if str(pk) in ids]

  @classmethod
  def initial_from_data(cls, data):
    """initial для перерисовки: что ввёл пользователь, без валидации и ошибок."""
    initial = {}
    for name in cls.base_fields:
      if name == 'discounts':
        initial[name] = data.getlist(name)
      elif name == 'price_fixed':
        initial[name] = data.get(name) in ('on', 'true', 'True', '1')
      elif name in data:
        initial[name] = data.get(name)
    return initial

  def clean(self):
    # До PriceManager.clean(): тот проверяет источник, а при фиксированной
    # цене в скрытом select мог остаться любой, в том числе из прайса.
    cleaned_data = super().clean()
    if cleaned_data.get('price_fixed'):
      cleaned_data['source'] = 'fixed_price'
    return cleaned_data

class PriceTagForm(forms.ModelForm):
  price_fixed = forms.BooleanField(widget=forms.widgets.CheckboxInput(), label='Фиксированная цена', required=False)
  source = forms.CharField(widget=forms.widgets.Select(choices=(
    (None, 'Не указано'),
    ('rrp', 'РРЦ в валюте поставщика'),
    ('supplier_price', 'Цена поставщика в валюте поставщика'),
    ('basic_price', 'Базовая цена'),
    ('prime_cost', 'Себестоимость'),
    ('m_price', 'Цена ИМ'),
    ('wholesale_price', 'Оптовая цена'),
    ('wholesale_price_extra', 'Оптовая цена1'))),
    label="От какой цены считать",
    required=False)
  class Meta:
    model = PriceTag
    fields = (
      'date_from', 'date_to',
      'source', 'dest',
      'price_fixed', 'fixed_price',
      'markup', 'increase',
    )
