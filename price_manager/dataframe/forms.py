from django import forms
from django.core.validators import FileExtensionValidator
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit, HTML, Button
from dal import autocomplete
from .models import ContentType, Dataframe, Link
from .utils import get_sheet_names, get_column_names, get_json_dicts, DICT_SCHEMA

from django_jsonform.forms.fields import JSONFormField
from django.urls import reverse


class FileUploadWidget(forms.ClearableFileInput):
    template_name = 'dataframe/widgets/filefield.html'


class DataFrameForm(forms.ModelForm):
    filefield = forms.FileField(widget=FileUploadWidget(), validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm', 'csv'])])
    sheet_name = forms.CharField(required=False)
    class Meta:
        model = Dataframe
        fields = ('filefield','sheet_name', 'name')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.file:
            self.fields['filefield'].required = False
            self.fields['filefield'].initial = self.instance.file.file
            # Always create a fresh Select widget with current sheet choices from the file
            sheet_choices = get_sheet_names(self.instance.file.pk)
            self.fields['sheet_name'].widget = forms.Select(
                choices=sheet_choices,
                attrs={'class': 'form-select'}
            )
        else:
            # No file yet — show placeholder
            self.fields['sheet_name'].widget = forms.Select(
                choices=[('', 'Выберите лист')],
                attrs={'class': 'form-select', 'disabled': True}
            )
    @property
    def helper(self):
        helper = FormHelper(self)
        helper.attrs={
            'hx-swap':"innerHTML",
            'hx-encoding': 'multipart/form-data',
            'hx-trigger':'submit, change',
            'hx-target':'#DataFrameForm',
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
        fields = ('contenttype', 'value', 'initial', 'dictitems')
        widgets = {
            'contenttype': autocomplete.ModelSelect2(
                url='dataframe:contenttype-autocomplete',
                attrs={'data-width': '100%'},
            )
        }
    dictitems = JSONFormField(schema=DICT_SCHEMA)

    def __init__(self, *args, **kwargs):
        self.file_pk = kwargs.pop('file_pk', None)
        self.sheet_name = kwargs.pop('sheet_name', None)
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['dictitems'].initial = get_json_dicts(self.instance.dicts.all())
        # Populate column choices from the linked file
        if self.file_pk:
            columns = get_column_names(self.file_pk, self.sheet_name)
            # Keep the existing value in the list even if the file changed
            if self.instance.pk and self.instance.value:
                if not any(v == self.instance.value for v, _ in columns):
                    columns.append((self.instance.value, f'{self.instance.value} ⚠ нет в файле'))
            self.fields['value'].widget = forms.Select(
                choices=columns,
                attrs={'class': 'form-select form-select-sm'},
            )
        else:
            self.fields['value'].widget = forms.Select(
                choices=[('', 'Сначала выберите файл')],
                attrs={'class': 'form-select form-select-sm', 'disabled': True},
            )
        self.fields['value'].required = False

    @property
    def helper(self):
        helper = FormHelper()
        helper.form_tag = False
        helper.layout = Layout(
            Div(
                Div(Field('contenttype'), css_class='flex-grow-1'),
                HTML('''<div class="flex-shrink-0 mb-3 d-flex align-items-end">
                          <button type="button"
                                  class="btn btn-outline-secondary"
                                  title="Создать новый тип контента"
                                  data-ct-create-btn>
                            <i class="bi bi-plus-lg"></i>
                          </button>
                        </div>'''),
                css_class='d-flex gap-2',
            ),
            Field('value'),
            Field('initial'),
            Field('dictitems'),
        )
        return helper


class LinkBaseFormset(forms.BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        self.file_pk = kwargs.pop('file_pk', None)
        self.sheet_name = kwargs.pop('sheet_name', None)
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['file_pk'] = self.file_pk
        kwargs['sheet_name'] = self.sheet_name
        return super()._construct_form(i, **kwargs)

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if 'DELETE' in form.fields:
            form.fields['DELETE'].widget = forms.HiddenInput()


LinkFormset = forms.modelformset_factory(Link, LinkForm, formset=LinkBaseFormset, can_delete=True)


class ContentTypeForm(forms.ModelForm):
    class Meta:
        model = ContentType
        fields = ('name', 'measure', 'contenttype')