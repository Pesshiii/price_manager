from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit, HTML, Button
from ..models import Dataframe, Link, DictItem
from ..utils import get_sheet_names

from django.urls import reverse


class LinkForm(forms.ModelForm):
    class Meta:
        model = Link
        fields = ("dataframe",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        self.helper.attrs = {
                'enctype':'multipart/form-data',
                'hx-post': reverse('dataframe:filecreate'),
                'hx-swap':'innerHTML',
                'hx-target':'#FileInput',
                }
        self.helper.layout = Layout(
            Submit(
                name='submit', 
                value='Выбрать',
                data_bs_toggle="modal",
                data_bs_target="#SelectFileModal",)
        )


class DataFrameForm(forms.ModelForm):
    file_pk = forms.IntegerField(widget=forms.widgets.HiddenInput())
    sheet_name = forms.CharField(widget=forms.Select(choices=[('', 'Выберите лист')]))
    class Meta:
        model = Dataframe
        fields = ('file_pk','sheet_name')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        if not self.instance.pk or self.instance.file is None:
            self.helper.form_method = 'post'
            self.helper.layout = Layout(
                Div(
                    Div(
                        Button(
                            name="button",
                            value="Добавить файл",
                            hx_get=reverse("dataframe:filelist"),
                            hx_target="#SelectFileContent",
                            hx_swap="innerHTML",
                            data_bs_toggle="modal",
                            data_bs_target="#SelectFileModal",
                        ),
                        css_id="FileInput"
                    ),
                    css_id="FormContents"
                )
            )
        else:
            
            self.helper.attrs={
                'hx-post':reverse('dataframe:update', kwargs={'pk':self.instance.pk}),
                'hx-swap':"innerHTML",
                'hx-trigger':'submit',
            }
            self.fields['file_pk'].initial = self.instance.file.pk
            self.fields['sheet_name'].choices = get_sheet_names(self.instance.file.pk)
            self.helper.layout = Layout(
                Div(
                    Field('name'),
                ),
                Div(
                    Field('sheet_name', css_class='form-select'),
                ),
                Div(
                    Field('file_pk'),
                    HTML('<span>{{object.file.filename}}</span>'),
                    Button(
                        name="button",
                        value="Добавить файл",
                        hx_get=reverse("dataframe:filelist"),
                        hx_target="#SelectFileContent",
                        hx_swap="innerHTML",
                        data_bs_toggle="modal",
                        data_bs_target="#SelectFileModal",
                    ),
                )
            )
