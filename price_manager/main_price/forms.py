from django import forms

from main_price.models import Category, MainProduct, Manufacturer, ManufacturerDict


class ManufacturerDictForm(forms.ModelForm):
    manufacturer = forms.ModelChoiceField(
        queryset=Manufacturer.objects.all(),
        label='',
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = ManufacturerDict
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        manufacturer_queryset = kwargs.pop('manufacturer_queryset', None)
        super().__init__(*args, **kwargs)
        if manufacturer_queryset is not None:
            self.fields['manufacturer'].queryset = manufacturer_queryset


class CategoryAddForm(forms.Form):
    category = forms.ModelChoiceField(
        Category.objects,
        label='Категория',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )


class MainProductForm(forms.ModelForm):
    name = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control w-50'}), label='Название')

    class Meta:
        model = MainProduct
        fields = '__all__'
