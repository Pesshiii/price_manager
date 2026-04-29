from django import forms

from .models import Dataframe


class Form(forms.ModelForm):
    class Meta:
        model = Dataframe
        fields = ["name", "conf", "cols"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "conf": forms.Textarea(attrs={"class": "form-control", "rows": 8}),
            "cols": forms.Textarea(attrs={"class": "form-control", "rows": 8}),
        }
