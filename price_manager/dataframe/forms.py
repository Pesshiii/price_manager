from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit
from django.core.exceptions import ObjectDoesNotExist

from .models import FileModel, Dataframe

from django.urls import reverse


class FileForm(forms.ModelForm):
    class Meta:
        model = FileModel
        fields = ("file",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        self.helper.attrs = {
                'enctype':'multipart/form-data',
                'hx-post': reverse('dataframe:filecreate'),
                'hx-swap':'innerHTML',
                'hx-target':'#SelectFile .modal-body',
                }
        self.helper.layout = Layout(
            Field('File'),
            Submit(value='Выбрать')
        )

class SelectFileForm(forms.ModelForm):
    pk = forms.IntegerField(widget=forms.widgets.HiddenInput())
    class Meta:
        model = FileModel
        fields = ("pk",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        if not self.instance:
            raise ObjectDoesNotExist()
        self.helper.attrs = {
                'hx-post': reverse('dataframe:filelist', kwargs={'pk':self.instance.pk}),
                'hx-swap':'innerHTML',
                'hx-target':'#SelectFile .modal-body',
                }
        self.helper.layout = Layout(
            Field('pk'),
            Submit(value='Выбрать')
        )
