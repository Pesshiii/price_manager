from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout, Submit
from django import forms
from django_jsonform.forms.fields import JSONFormField

from .models import Dataframe


class Form(forms.ModelForm):
    conf = JSONFormField(label="Настройка", schema=Dataframe.CONF_SCHEMA)

    class Meta:
        model = Dataframe
        fields = ["name", "conf", "cols"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.layout = Layout(
            Field('name'),
            Field('conf'),
            Submit(name='save', value="Сохранить")
        )