from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit, HTML, Button
from django.core.exceptions import ObjectDoesNotExist

from ..models import FileModel

from django.urls import reverse


class UploadFileForm(forms.ModelForm):
    class Meta:
        model = FileModel
        fields = ("file",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        self.helper.attrs = {
                'hx-encoding': 'multipart/form-data',
                'hx-post': reverse('dataframe:filecreate'),
                'hx-swap':'innerHTML',
                'hx-target':'#FileInput',
                }
        self.helper.layout = Layout(
            Field('file'),
            Submit(
                name='submit', 
                value='Выбрать',
                data_bs_toggle="modal",
                data_bs_target="#SelectFileModal",)
        )
