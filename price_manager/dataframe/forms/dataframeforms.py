from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit, HTML, Button
from ..models import Dataframe, Link, DictItem
from ..utils import get_sheet_names

from django.urls import reverse


class DataFrameForm(forms.ModelForm):
    file_pk = forms.IntegerField(widget=forms.widgets.HiddenInput())
    sheet_name = forms.CharField(widget=forms.Select(choices=[('', 'Выберите лист')]))
    class Meta:
        model = Dataframe
        fields = ('file_pk','sheet_name', 'name')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.file:
            self.fields['file_pk'].initial = self.instance.file.pk
            self.fields['sheet_name'].widget.choices = get_sheet_names(self.instance.file.pk)
    
    @property
    def helper(self):
        helper = FormHelper(self)
        if not self.instance.pk or self.instance.file is None:
            helper.form_method = 'post'
            helper.layout = Layout(
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
                            css_class="btn btn-primary",
                        ),
                        css_id="FileInput"
                    ),
                    css_id="FormContents"
                )
            )
        else:
            
            helper.attrs={
                'hx-post':reverse('dataframe:update', kwargs={'pk': self.instance.pk}),
                'hx-swap':"innerHTML",
                'hx-trigger':'submit',
                'hx-push-url':'true',
            }
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
                                css_class="btn btn-secondary",
                            ),
                            css_class='mt-4 mb-4'
                        ),
                        Submit(name='submit', value='Сохранить'),
                        css_class='col-8',
                    ),
                    Div(
                        HTML('''
                             {% include "datarame/contenttype/list.html"%}
                             '''),
                        css_class='row-8',
                    ),
                    css_class='row',
                )
            )
        return helper
