from django import forms
from django.db.models.functions import Lower
from django.db.models import Q

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

class SettingForm(forms.ModelForm):
  sheet_name = forms.ChoiceField()
  supplier = forms.ModelChoiceField(
    Supplier.objects,
    widget=forms.HiddenInput,
    required=False
  )
  class Meta:
    model = Setting
    fields = ['name', 'sheet_name', 'priced_only', 'id_as_sku', 'currency', 'supplier']

class LinksForm(forms.Form):
  """Форма для связки столбцы/дата_поинты"""
  link = forms.CharField(widget=forms.Select(choices=LINKS),
                         label='',
                         required=False,
                         initial=LINKS[0])
  class Meta:
    fields = ['link']

class FileForm(forms.ModelForm):
  class Meta:
    model = FileModel
    fields = '__all__'

class FilterForm(forms.Form):
  search = forms.CharField(label='Поиск по всем полям',
                           required=False,
                           widget=forms.TextInput(attrs={
                             'class':'w-100'
                           }))
  name = forms.CharField(label='Название',
                           required=False)
  manufacturer = forms.ModelChoiceField(Manufacturer.objects,
                                        label='Производитель',
                                        required=False)
  def filter_queryset(self, queryset, request):
    if 'name' in request and not request['name'] == '':
      queryset = queryset.annotate(
        lower_name=Lower('name')).filter(
          lower_name__icontains=request['name'].lower()
          )
    if 'manufacturer' in request and not request['manufacturer'] == '':
      queryset = queryset.filter(manufacturer_id=request['manufacturer'])
    return queryset
  
  
class SupplierFilterForm(FilterForm):
  sku = forms.CharField(label='Назвние в главном прайсе',
                              required=False)
  def filter_queryset(self, queryset, request):
    queryset = super().filter_queryset(queryset, request)
    if 'sku' in request and not request['sku'] == '':
      queryset = queryset.annotate(
        lower_name=Lower('sku__name')).filter(
          lower_name__icontains=request['sku'].lower()
      )
    return queryset
  
class MainProductFilterForm(FilterForm):
  supplier = forms.ModelChoiceField(Supplier.objects,
                                    label='Поставщик',
                                    required=False)
  def filter_queryset(self, queryset, request):
    queryset = super().filter_queryset(queryset, request)
    if 'supplier' in request and not request['supplier'] == '':
      queryset = queryset.filter(
          supplier_id=request['supplier']
      )
    return queryset

class SortSupplierProductFilterForm(SupplierFilterForm):
  supplier = forms.ModelChoiceField(Supplier.objects,
                                    label='Поставщик',
                                    required=False)
  def filter_queryset(self, queryset, request):
    queryset = super().filter_queryset(queryset, request)
    if 'supplier' in request and not request['supplier'] == '':
      queryset = queryset.filter(supplier_id=request['supplier'])
    return queryset

class CategoryAddForm(forms.Form):
  # Используется при связке категории с товарами
  category = forms.ModelChoiceField(
    Category.objects,
    label='Категория',
    widget=forms.Select(attrs={
      'class':'form-select'
    })
  )


class DictForm(forms.ModelForm):
  link = forms.ModelChoiceField(Link.objects,
                                required=False,
                                widget=forms.HiddenInput(),
                                label='')
  enable = forms.BooleanField(label='',
                              initial=True)
  class Meta:
    model = Dict
    fields = '__all__'

DictFormSet = forms.formset_factory(DictForm, extra=0)
