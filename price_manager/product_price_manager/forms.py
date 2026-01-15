from django import forms
from .models import PriceManager, PriceTag


class PriceManagerForm(forms.ModelForm):
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
    model = PriceManager
    fields = (
      'name',
      'has_rrp',
      'date_from', 'date_to',
      'price_from', 'price_to',
      'source', 'dest',
      'price_fixed', 'fixed_price',
      'markup', 'increase',
    )

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
