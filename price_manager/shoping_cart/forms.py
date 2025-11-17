from django import forms

from shoping_cart.models import AlternateProduct, ShopingTab


class ShopingTabCreateForm(forms.ModelForm):
    class Meta:
        model = ShopingTab
        fields = ['name']
        labels = {'name': 'Название корзины'}
        widgets = {'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например, Заказ №1'})}


class ShopingTabUpdateForm(forms.ModelForm):
    class Meta:
        model = ShopingTab
        fields = ['name', 'open']
        labels = {'name': 'Название', 'open': 'Открыта'}
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'open': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AlternateProductForm(forms.ModelForm):
    class Meta:
        model = AlternateProduct
        fields = ['name']
        labels = {'name': 'Название'}
        widgets = {'name': forms.TextInput(attrs={'class': 'form-control'})}
