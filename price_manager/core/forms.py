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
    fields = '__all__'


class ShoppingTabForm(forms.ModelForm):
  def __init__(self, *args, user=None, **kwargs):
    self.user = user
    super().__init__(*args, **kwargs)

  def clean_name(self):
    name = (self.cleaned_data.get('name') or '').strip()
    if not name:
      raise forms.ValidationError('Название заявки обязательно.')

    queryset = ShopingTab.objects.all()
    if self.instance and self.instance.pk:
      queryset = queryset.exclude(pk=self.instance.pk)
      owner = self.instance.user
    else:
      owner = self.user

    if owner is not None and queryset.filter(user=owner, name=name).exists():
      raise forms.ValidationError('Заявка с таким названием уже существует.')

    return name

  class Meta:
    model = ShopingTab
    fields = ['name', 'open']
    widgets = {
      'name': forms.TextInput(attrs={'class': 'form-control'}),
      'open': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    }
    labels = {
      'name': 'Название заявки',
      'open': 'Заявка открыта',
    }


class ShoppingTabSelectionForm(forms.Form):
  NEW_TAB_VALUE = '__new__'

  tab = forms.ChoiceField(
    required=True,
    widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
    label='Заявка'
  )
  new_tab_name = forms.CharField(
    required=False,
    label='Название новой заявки',
    widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например, Заявка от сегодня'})
  )
  quantity = forms.IntegerField(
    min_value=1,
    initial=1,
    label='Количество',
    widget=forms.NumberInput(attrs={'class': 'form-control'})
  )

  def __init__(self, *args, user=None, tabs=None, **kwargs):
    self.user = user
    self.tabs = list(tabs) if tabs is not None else []
    super().__init__(*args, **kwargs)

    choices = [(self.NEW_TAB_VALUE, 'Создать новую заявку')]
    choices.extend((str(tab.pk), tab.name) for tab in self.tabs)
    self.fields['tab'].choices = choices
    if 'tab' not in self.initial:
      self.initial['tab'] = self.NEW_TAB_VALUE
    self.fields['tab'].initial = self.initial.get('tab', self.NEW_TAB_VALUE)

  def clean_quantity(self):
    quantity = self.cleaned_data.get('quantity')
    if quantity is None or quantity < 1:
      raise forms.ValidationError('Количество должно быть больше нуля.')
    return quantity

  def clean(self):
    cleaned_data = super().clean()
    selected_tab = cleaned_data.get('tab')
    new_name = (cleaned_data.get('new_tab_name') or '').strip()

    if not selected_tab:
      raise forms.ValidationError('Выберите заявку или создайте новую.')

    if selected_tab == self.NEW_TAB_VALUE:
      if not new_name:
        self.add_error('new_tab_name', 'Укажите название для новой заявки.')
        raise forms.ValidationError('Название заявки обязательно.')

      if self.user and ShopingTab.objects.filter(user=self.user, name=new_name).exists():
        self.add_error('new_tab_name', 'Заявка с таким названием уже существует.')
        raise forms.ValidationError('Название должно быть уникальным.')

      cleaned_data['new_tab_name'] = new_name
      cleaned_data['tab_instance'] = None
      return cleaned_data

    tab_lookup = {str(tab.pk): tab for tab in self.tabs}
    tab_instance = tab_lookup.get(str(selected_tab))
    if not tab_instance:
      raise forms.ValidationError('Выберите корректную заявку.')

    cleaned_data['tab_instance'] = tab_instance
    cleaned_data['new_tab_name'] = ''
    return cleaned_data
