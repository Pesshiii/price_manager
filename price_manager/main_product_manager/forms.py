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


class MainProductBulkCategoryForm(forms.Form):
  category = forms.ModelChoiceField(
    label='Категория',
    queryset=Category.objects.all(),
    required=True,
    empty_label='Выберите категорию',
  )

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.fields['category'].queryset = Category.objects.all().order_by('tree_id', 'lft')
