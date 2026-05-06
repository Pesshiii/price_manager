from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Submit
from django.urls import reverse

from ..models import ContentType


class ContentTypeForm(forms.ModelForm):
    class Meta:
        model = ContentType
        fields = ("name", "measure", "contenttype")
    @property
    def helper(self):
        helper = FormHelper(self)
        helper.form_method = 'post'
        helper.attrs = {
                'hx-post': reverse('dataframe:contenttypecreate')
                }
        helper.layout = Layout(
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
        return helper

