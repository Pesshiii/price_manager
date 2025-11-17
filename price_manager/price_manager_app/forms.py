from django import forms

from price_manager_app.models import PriceManager


class PriceManagerForm(forms.ModelForm):
    class Meta:
        model = PriceManager
        fields = '__all__'
