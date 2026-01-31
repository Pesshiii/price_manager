from django import forms
from .models import PriceManager


class PriceManagerForm(forms.ModelForm):
  class Meta:
    model = PriceManager
    fields = '__all__'