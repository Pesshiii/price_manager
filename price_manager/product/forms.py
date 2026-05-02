from django import forms

from .models import ContentType


class ContentTypeForm(forms.ModelForm):
    class Meta:
        model = ContentType
        fields = ("name", "measure", "contenttype")
