from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit, HTML, Button
from ..models import Link, DictItem
from ..utils import get_sheet_names

from django.urls import reverse


class LinkForm(forms.ModelForm):
    class Meta:
        model = Link
        fields = ("initial", "contenttype", "value")
    def __init__(self, *args, **kwargs):
        df_pk = kwargs.pop('df_pk', None)
        super().__init__(*args, **kwargs)
        self.df_pk = df_pk
    @property
    def helper(self):
        helper = FormHelper(self)
        helper.form_method = 'post'
        helper.layout = Layout(
            HTML('<span>{{object.contenttype}}</span>'),
            Field('initial'),
            Field('value', css_class='form-select'),
            Submit(
                name='delete', 
                value='X',
                css_class='btn btn-danger',
                )
        )
        return helper

