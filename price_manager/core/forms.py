from django import forms
from django.db.models.functions import Lower
from django.db.models import Q
from .models import PriceManager, Discount

from .models import *

class SupplierForm(forms.ModelForm):
  class Meta:
    model = Supplier
    fields = '__all__'

class ManufacturerDictForm(forms.ModelForm):
  manufacturer = forms.ModelChoiceField(Manufacturer.objects,
                                        label='',
                                        widget=forms.HiddenInput())
  class Meta:
    model = ManufacturerDict
    fields = '__all__'



class FileForm(forms.ModelForm):
  class Meta:
    model = FileModel
    fields = '__all__'
  

class CategoryAddForm(forms.Form):
  # Используется при связке категории с товарами
  category = forms.ModelChoiceField(
    Category.objects,
    label='Категория',
    widget=forms.Select(attrs={
      'class':'form-select'
    })
  )



class MainProductForm(forms.ModelForm):
  name = forms.CharField(widget=forms.Textarea(attrs={'class':'form-control w-50'}),
                         label='Название')
  class Meta:
    model = MainProduct
    fields = '__all__'

# Формы для редактирования/создания настроек
class SettingForm(forms.ModelForm):
  sheet_name = forms.ChoiceField(label='Лист')
  supplier = forms.ModelChoiceField(
    Supplier.objects,
    label='',
    widget=forms.HiddenInput,
    required=False
  )
  currency = forms.ModelChoiceField(
    Currency.objects,
    label='Валюта',
    required=True,
    initial=Currency.objects.get(name='KZT')
  )
  class Meta:
    model = Setting
    fields = '__all__'

class LinkForm(forms.Form):
  """Форма для связки в Link"""
  key = forms.CharField(widget=forms.Select(choices=LINKS),
                         label='',
                         required=False,
                         initial=LINKS[''])
  value = forms.CharField(label='', widget=forms.HiddenInput)
  class Meta:
    fields = ['key', 'value']

class DictForm(forms.Form):
  key = forms.CharField(label='', required=False, widget=forms.TextInput(attrs={'class':'w-100'}))
  value = forms.CharField(label='', required=False, widget=forms.TextInput(attrs={'class':'w-100'}))

class InitialForm(forms.Form):
  """Форма для задания начальных значений"""
  initial = forms.CharField(label='Начальное значение',
                            required=False,
                            empty_value='')
  

class PriceManagerForm(forms.ModelForm):
  class Meta:
    model = PriceManager
    fields = ['name', 'supplier', 'discounts', 'source', 'dest', 'price_from', 'price_to', 'markup', 'increase']

# class PriceManagerAdminForm(forms.ModelForm):
#     class Meta:
#         model = PriceManager
#         fields = ['name', 'supplier', 'discount', 'source', 'dest', 'price_from', 'price_to', 'markup', 'increase']

#     def __init__(self, *args, **kwargs):
#         # request передадим из админ-класса
#         request = kwargs.pop('request', None)
#         super().__init__(*args, **kwargs)

#         # По умолчанию список скидок пуст, пока не выбран поставщик
#         self.fields['discount'].queryset = Discount.objects.none()
#         self.fields['discount'].widget.attrs['data-placeholder'] = 'Сначала выберите поставщика'

#         supplier_id = None

#         # 1) При первом заходе/редактировании — из инстанса
#         if getattr(self.instance, 'supplier_id', None):
#             supplier_id = self.instance.supplier_id

#         # 2) При отправке формы/перерисовке — из данных запроса
#         # (работает и на POST, и на GET при автосабмите)
#         # Django передает значения в self.data как строки
#         if request is not None:
#             supplier_id = request.POST.get('supplier') or request.GET.get('supplier') or supplier_id

#         if supplier_id:
#             self.fields['discount'].queryset = Discount.objects.filter(supplier_id=supplier_id).order_by('name')

