from django import forms

from supplier_manager.models import Supplier


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = '__all__'
