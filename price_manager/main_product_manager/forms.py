from django import forms
from .models import Supplier, Manufacturer, Category, MainProduct


class MainProductForm(forms.ModelForm):
  class Meta:
    model = MainProduct
    fields = (
      'sku',
      'weight',
      'length',
      'width',
      'depth',
    )
