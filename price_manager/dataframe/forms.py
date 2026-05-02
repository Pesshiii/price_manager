from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, HTML

from .models import Dataframe, FileModel


class FileForm(forms.ModelForm):
    class Meta:
        model = FileModel
        fields = ("file",)
