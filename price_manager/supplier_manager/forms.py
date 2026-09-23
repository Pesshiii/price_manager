from django import forms
from .models import Supplier
from django.urls import reverse_lazy
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML


INTERVAL_UNITS = [('day', 'дней'), ('week', 'недель')]
UNIT_DAYS = {'day': 1, 'week': 7}


class IntervalWidget(forms.MultiWidget):
  '''Число + единица (дни/недели) в одной input-group.'''
  template_name = 'supplier/widgets/interval.html'

  def __init__(self, attrs=None):
    widgets = [
      forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'placeholder': 'не отслеживать'}),
      forms.Select(choices=INTERVAL_UNITS, attrs={'class': 'form-select flex-grow-0 w-auto'}),
    ]
    super().__init__(widgets, attrs)

  def decompress(self, value):
    if not value:
      return [None, 'day']
    if value % 7 == 0:
      return [value // 7, 'week']
    return [value, 'day']


class IntervalField(forms.MultiValueField):
  '''Интервал в днях, вводимый как «число + дни/недели». Пустое число — None.'''
  widget = IntervalWidget

  def __init__(self, **kwargs):
    kwargs.pop('max_value', None)
    kwargs.pop('min_value', None)
    fields = [
      forms.IntegerField(min_value=1, required=False),
      forms.ChoiceField(choices=INTERVAL_UNITS, required=False),
    ]
    super().__init__(fields, require_all_fields=False, **kwargs)

  def compress(self, data_list):
    if not data_list or data_list[0] in (None, ''):
      return None
    amount, unit = data_list
    return amount * UNIT_DAYS.get(unit or 'day', 1)


class SupplierForm(forms.ModelForm):
  class Meta:
    model = Supplier
    fields = [
      'name',
      'delivery_days_available',
      'delivery_days_navailable',
      'currency',
      'sku_type',
      'sku_value',
      'price_update_days',
      'stock_update_days',
      'msg_available',
      'msg_navailable',
      'price_priority',
      'stock_priority',
    ]
    help_texts = {
      'price_update_days': 'Пусто — не отслеживать.',
      'stock_update_days': 'Пусто — не отслеживать.',
    }
    field_classes = {
      'price_update_days': IntervalField,
      'stock_update_days': IntervalField,
    }
  def __init__(self, *args, **kwargs):
    url = kwargs.pop('url', None)
    if not url: return None
    super().__init__(*args, **kwargs)
    self.helper = FormHelper(self)
    self.helper.form_method = 'POST'
    self.helper.label_class='mt-4'
    self.helper.attrs = {
      'hx-post':url,
      'hx-target':'#supplier-update',
      'hx-swap':'outerHTML',
      'hx-trigger':'submit',
    }
    self.helper.layout = Layout(
      Div(
        Div('name', css_class='col-8'),
        css_class='row',
      ),
      Div(
        Div(
          Field('currency', css_class='form-select'), 
          css_class='col-8'
        ), 
        css_class='row'
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(
        Div('price_update_days', css_class="col-4"),
        Div('stock_update_days', css_class="col-4"),
        css_class='row'
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(
        Div(
            Field('sku_type', css_class='form-select'), css_class="col-4"),
            Div('sku_value', css_class="col-4"),
            css_class='row'
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(
        Div('delivery_days_available', css_class='col-4'),
        Div('delivery_days_navailable', css_class='col-4'),
        css_class='row',
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(
        Div(
        Field('msg_available', css_class='form-control'), css_class="col-4"),
        Div(
        Field('msg_navailable', css_class='form-control'),css_class="col-4"),
        css_class='row mb-4'
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Div(
        Div('price_priority', css_class='col-4'),
        Div('stock_priority', css_class='col-4'),
        css_class='row',
      ),
      HTML('<hr class="my-4 border-secondary col-8">'),
      Submit('action', 'Сохранить', title="Поиск", css_class='btn btn-primary col-5 mt-4 btn-lg')
    )
