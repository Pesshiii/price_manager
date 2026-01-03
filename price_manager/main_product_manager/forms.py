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

# class MainProductFilter(forms.Form):
#   def __init__(self, *args, **kwargs):
#     super().__init__(*args, **kwargs)
#     self.helper = FormHelper(self)
#     self.helper.form_action = reverse_lazy('mainproduct-filter')
#     self.helper.form_method = 'GET'
#     self.helper.add_input(Submit('submit', 'Поиск'))

#   search = forms.CharField(widget=forms.TextInput(attrs={'hx-get':reverse_lazy('mainproduct-filter'), 'hx-trigger':'keyup'}))