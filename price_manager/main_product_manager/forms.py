from django import forms
from django.db.models import Q
from django.utils import timezone

from .models import Supplier, MainProduct, MP_PRICES

SKU_MAX_LENGTH = 128  # product.Product.number — артикул строки становится им


class MainProductForm(forms.ModelForm):
  """Строка ГП — создание и правка, одной формой.

  Строка может быть без поставщика: набор, остаток на складе, возврат, бонус —
  то, для чего заводить поставщика с выгрузкой незачем. Цены и остаток
  вводятся руками; наценки потом могут их пересчитать (см. price_rules в
  шаблоне — подсказка у каждой цены, которой это грозит).

  Что форма не даёт менять:
  - у строки из прайса поставщика — поставщика и артикул поставщика: по ним
    её находит импорт, и следующая загрузка прайса завела бы строку заново;
  - у строки набора — поставщика, артикул и себестоимость: себестоимость —
    сумма комплектующих (product.services.set_rows);
  - при создании из карточки товара — артикул: он и есть товар.
  """

  class Meta:
    model = MainProduct
    fields = ('sku', 'supplier', 'article', 'name', 'note', 'stock', *MP_PRICES)
    labels = {
      'sku': 'Артикул товара',
      'article': 'Артикул поставщика',
      'name': 'Название',
      'note': 'Комментарий',
      'wholesale_price_extra': 'Оптовая цена доп.',
    }
    help_texts = {
      'note': 'Зачем строка: возврат, бонус, остаток на складе…',
    }

  def __init__(self, *args, product=None, **kwargs):
    # Модалка открывается поверх «Товаров» и карточки, у фильтра «Товаров»
    # есть поле supplier — без префикса id и name совпали бы.
    kwargs['prefix'] = kwargs.get('prefix') or 'mp'
    super().__init__(*args, **kwargs)
    self.product = product
    instance = self.instance
    self.from_price_list = bool(instance.pk) and instance.has_supplier_price_list
    self.is_set_row = bool(instance.pk) and instance.is_set

    supplier = self.fields['supplier']
    supplier.queryset = Supplier.objects.order_by('name')
    supplier.empty_label = 'Без поставщика'
    supplier.required = False
    self.fields['article'].required = False
    self.fields['sku'].required = True
    self.fields['sku'].max_length = SKU_MAX_LENGTH
    self.fields['sku'].widget.attrs['maxlength'] = SKU_MAX_LENGTH
    # null=True без blank=True — ModelForm сделал бы их обязательными, а
    # пустое поле здесь значит «нет данных».
    for name in ('stock', *MP_PRICES):
      self.fields[name].required = False
    self.fields['stock'].min_value = 0
    self.fields['stock'].widget.attrs['min'] = 0
    for field in MP_PRICES:
      self.fields[field].widget.attrs.update({'min': 0, 'step': '0.01', 'inputmode': 'decimal'})

    if product is not None and not instance.pk:
      self.initial.setdefault('sku', product.number)
      self.initial.setdefault('name', product.name or product.display_name)
      if product.number:
        self.fields['sku'].disabled = True
    if self.from_price_list:
      self.fields['supplier'].disabled = True
      self.fields['article'].disabled = True
    if self.is_set_row:
      for name in ('supplier', 'sku', 'article', 'prime_cost'):
        self.fields[name].disabled = True

  @property
  def price_fields(self):
    return [self[name] for name in MP_PRICES]

  def clean_sku(self):
    sku = (self.cleaned_data.get('sku') or '').strip()
    if not sku:
      raise forms.ValidationError('Укажите артикул товара')
    if self.product is not None and not self.product.number:
      from product.models import Product
      if Product.objects.filter(number__iexact=sku).exclude(pk=self.product.pk).exists():
        raise forms.ValidationError('Этот артикул уже у другого товара')
    return sku

  def clean_note(self):
    return (self.cleaned_data.get('note') or '').strip()

  def clean(self):
    cleaned_data = super().clean()
    supplier = cleaned_data.get('supplier')
    article = (cleaned_data.get('article') or '').strip()
    if not article:
      if supplier is not None:
        self.add_error('article', 'У строки поставщика нужен его артикул')
      # У строки без поставщика своего кода нет — им служит артикул товара.
      article = cleaned_data.get('sku') or ''
    cleaned_data['article'] = article
    name = cleaned_data.get('name')
    if article and name:
      duplicates = MainProduct.objects.filter(supplier=supplier, article=article, name=name)
      if self.instance.pk:
        duplicates = duplicates.exclude(pk=self.instance.pk)
      if duplicates.exists():
        raise forms.ValidationError('Строка ГП с таким поставщиком, артикулом и названием уже есть.')
    return cleaned_data

  def price_log_entries(self):
    """Записи истории для цен и остатка, изменённых в этой форме."""
    from .models import MainProductLog
    entries = []
    for name in self.changed_data:
      if name in MP_PRICES:
        entries.append(MainProductLog(main_product=self.instance, price_type=name,
                                      price=self.cleaned_data.get(name)))
      elif name == 'stock':
        entries.append(MainProductLog(main_product=self.instance, stock=self.cleaned_data.get('stock')))
    return entries

  def stamp_updates(self):
    """Время последнего обновления цены и остатка — если они правда менялись."""
    now = timezone.now()
    if any(name in MP_PRICES for name in self.changed_data):
      self.instance.price_updated_at = now
    if 'stock' in self.changed_data:
      self.instance.stock_updated_at = now
