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
        if not self.instance.pk:
            helper.attrs = {
                    'hx-post': reverse('dataframe:linkcreate'),
                    }
            helper.layout = Layout(
                Div(
                    Div(
                        Button(
                            name="button",
                            value="Добавить связь",
                            hx_get=reverse("dataframe:contenttypelist", kwargs={'df_pk':self.df_pk}),
                            hx_target="#SelectContentTypeContent",
                            hx_swap="innerHTML",
                            data_bs_toggle="modal",
                            data_bs_target="#SelectContentTypeModal",
                            css_class="btn btn-primary",
                        ),
                        css_id="ContentTypeInputNew"
                    ),
                    css_id="FormContentsNew"
                )
            )
        else:
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

