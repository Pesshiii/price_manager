from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Submit
from django.urls import reverse

from ..models import ContentType


class ContentTypeForm(forms.ModelForm):
    class Meta:
        model = ContentType
        fields = ("name", "measure", "contenttype")
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        self.helper.attrs = {
                'hx-encoding': 'multipart/form-data',
                'hx-post': reverse('dataframe:filecreate')
                }
        self.helper.layout = Layout(
            Field('name'),
            Field('mesure'),
            Field('contenttype'),
            Submit(
                name='submit', 
                value='Выбрать',
                data_bs_toggle="modal",
                data_bs_target="#SelectContentTypeModal",
                )
        )
