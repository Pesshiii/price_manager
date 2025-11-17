from django import forms

from setting_manager.models import Dict, Link, Setting, LINKS
from supplier_manager.models import Supplier


class SettingForm(forms.ModelForm):
    sheet_name = forms.ChoiceField(label='Лист')
    supplier = forms.ModelChoiceField(
        Supplier.objects,
        label='',
        widget=forms.HiddenInput,
        required=False,
    )

    class Meta:
        model = Setting
        fields = '__all__'


class LinkForm(forms.Form):
    key = forms.CharField(
        widget=forms.Select(choices=LINKS),
        label='',
        required=False,
        initial=LINKS[''],
    )
    value = forms.CharField(label='', widget=forms.HiddenInput)


class DictForm(forms.Form):
    key = forms.CharField(label='', required=False, widget=forms.TextInput(attrs={'class': 'w-100'}))
    value = forms.CharField(label='', required=False, widget=forms.TextInput(attrs={'class': 'w-100'}))


class InitialForm(forms.Form):
    initial = forms.CharField(label='Начальное значение', required=False, empty_value='')
