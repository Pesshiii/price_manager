from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout, Submit, HTML
from django import forms
from django_jsonform.forms.fields import JSONFormField
from django.urls import reverse

from .models import Dataframe


class Form(forms.ModelForm):
    conf = JSONFormField(label="Настройка", schema=Dataframe.CONF_SCHEMA)
    cols = JSONFormField(label="Столбцы", schema=Dataframe.COLS_SCHEMA)

    class Meta:
        model = Dataframe
        fields = ["name", "conf", "cols"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        
        self.helper.attrs = {
            'hx-get':reverse('dataframe:create'),
            'hx-swap':'innerHTML',
            'hx-trigger':'input changed delay:2s, change delay:2s, submit',
            'hx-push-url':'true'
        }
        self.helper.layout = Layout(
            Field('name'),
            Field('conf'),
            Field('cols'),
            Submit(name='save', value="Сохранить")
        )