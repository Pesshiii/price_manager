from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Submit
from ..models import FileModel

from django.urls import reverse


class FileForm(forms.ModelForm):
    class Meta:
        model = FileModel
        fields = ("file",)
    @property
    def helper(self):
        helper = FormHelper(self)
        helper.form_method = 'post'
        helper.attrs = {
                'hx-post': reverse('dataframe:filecreate')
                }
        helper.layout = Layout(
            Field('file'),
            Submit(
                name='submit', 
                value='Выбрать',
                data_bs_toggle="modal",
                data_bs_target="#SelectFileModal",)
        )
        return helper