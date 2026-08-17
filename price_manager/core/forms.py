from django import forms
from core.models import CartItem, ShoppingTab, AlternateProduct, ShoppingTab
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field


class ShoppingTabCreateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
        Field('name', css_class='form-control'),
        Field('file', css_class='form-control'),
        Submit('submit', 'Создать', css_class='btn btn-primary')
        )
    
    class Meta:
        model = ShoppingTab
        fields = ['name', 'file']

class ShoppingTabUpdateForm(forms.ModelForm):
    class Meta:
        model = ShoppingTab
        fields = ['name', 'file', 'open']
        labels = {
        'name': 'Название',
        'file': 'Файл',
        'open': 'Открыта',
        }
        widgets = {
        'name': forms.TextInput(attrs={'class': 'form-control'}),
        'file': forms.FileInput(attrs={'class': 'form-control'}),
        'open': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CartItemForm(forms.ModelForm):
    class Meta:
        model = CartItem
        fields = ['query', 'quantity']
        labels = {
            'query': 'Запрос',
            'quantity': 'Количество',
        }
        widgets = {
            'query': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
        }
