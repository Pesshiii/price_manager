from django import forms
from django.core.validators import FileExtensionValidator
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit, HTML, Button
from dal import autocomplete
from .models import ContentType, Dataframe, Link
from .utils import get_sheet_names, get_json_dicts, DICT_SCHEMA

from django_jsonform.forms.fields import JSONFormField
from django.urls import reverse


class FileUploadWidget(forms.ClearableFileInput):
    template_name = 'dataframe/widgets/filefield.html'


class DataFrameForm(forms.ModelForm):
    filefield = forms.FileField(widget=FileUploadWidget(), validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm', 'csv'])])
    sheet_name = forms.CharField(widget=forms.Select(choices=[('', 'Выберите лист')]), required=False)
    class Meta:
        model = Dataframe
        fields = ('filefield','sheet_name', 'name')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.file:
            self.fields['filefield'].required = False
            self.fields['filefield'].initial = self.instance.file.file
            self.fields['sheet_name'].widget.choices = get_sheet_names(self.instance.file.pk)
    @property
    def helper(self):
        helper = FormHelper(self)
        helper.attrs={
            'hx-swap':"innerHTML",
            'hx-encoding': 'multipart/form-data',
            'hx-trigger':'submit, change',
            'hx-target':'DataFrameForm',
            'hx-push-url':'true',
        }
        add_ons=[]
        if self.instance.pk:
            add_ons.append(Div(
                    HTML('''{% include "dataframe/linkformset.html" with formset=formset %}'''),
                    css_class='col-6',
                ))
            helper.attrs['hx-post']=reverse('dataframe:update', kwargs={'pk': self.instance.pk})
        else:
            helper.attrs['hx-post']=reverse('dataframe:create')
        helper.layout = Layout(
            Div(
                Div(
                    Div(
                        Field('name'),
                    ),
                    Div(
                        Field('sheet_name', css_class='form-select'),
                    ),
                    Div(
                        Field('filefield'),
                    ),
                    css_class='col-6',
                ),
                *add_ons,
                css_class='row',
            ),
            Div(
                Submit(name='submit', value='Сохранить'),
                css_class='row',
            )
        )
        return helper


class LinkForm(forms.ModelForm):
    class Meta:
        model = Link
        fields = ('contenttype', 'initial', 'dictitems')
        widgets = {
            'contenttype': autocomplete.ModelSelect2(
                url='dataframe:contenttype-autocomplete',
                attrs={'data-width': '100%'},
            )
        }
    dictitems = JSONFormField(schema=DICT_SCHEMA)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['dictitems'].initial = get_json_dicts(self.instance.dicts.all())
        if 'DELETE' in self.fields:
            self.fields['DELETE'].widget = forms.HiddenInput()

LinkFormset = forms.modelformset_factory(Link, LinkForm, can_delete=True)


class ContentTypeForm(forms.ModelForm):
    class Meta:
        model = ContentType
        fields = ('name', 'measure', 'contenttype')