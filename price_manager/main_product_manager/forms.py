from django import forms
from .models import Supplier, Manufacturer, Category, MainProduct


class MainProductForm(forms.ModelForm):
  name = forms.CharField(widget=forms.Textarea(attrs={'class':'form-control w-50'}),
                         label='Название')
  class Meta:
    model = MainProduct
    fields = '__all__'

