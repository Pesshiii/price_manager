from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout
from core.crispy_fields import CustomRadio
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


class MainProductCreateForm(forms.ModelForm):
  class Meta:
    model = MainProduct
    fields = (
      'supplier',
      'article',
      'name',
      'sku',
      'manufacturer',
      'categories',
      'stock',
      'weight',
      'length',
      'width',
      'depth',
    )
    widgets = {
      'supplier': forms.RadioSelect(),
      'manufacturer': forms.RadioSelect(),
    }

  def __init__(self, *args, **kwargs):
    # The create modal overlays mainproducts' list page without removing it from the
    # DOM, and MainProductFilter has fields with the same names (supplier, manufacturer,
    # categories) — without a prefix this form's auto_id/html_name would collide with
    # the filter sidebar's, so a <label for="id_supplier_0"> click in the modal could
    # toggle the filter's checkbox instead of this form's radio.
    kwargs.setdefault('prefix', 'mpcreate')
    super().__init__(*args, **kwargs)
    self.fields['supplier'].queryset = Supplier.objects.order_by('name')
    self.fields['manufacturer'].queryset = Manufacturer.objects.order_by('name')
    # categories is rendered separately by MainProductCreateCategoryTree (a lazy-loaded
    # tree widget), not by this crispy layout — see mainproduct/partials/create.html.
    self.helper = FormHelper(self)
    self.helper.form_tag = False
    self.helper.layout = Layout(
      CustomRadio('supplier'),
      'article',
      'name',
      'sku',
      CustomRadio('manufacturer'),
      'stock',
      'weight',
      'length',
      'width',
      'depth',
    )

  def clean(self):
    cleaned_data = super().clean()
    supplier = cleaned_data.get('supplier')
    article = cleaned_data.get('article')
    name = cleaned_data.get('name')
    if article and name and MainProduct.objects.filter(supplier=supplier, article=article, name=name).exists():
      raise forms.ValidationError(
        'Главный продукт с таким поставщиком, артикулом и названием уже существует.'
      )
    return cleaned_data


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
