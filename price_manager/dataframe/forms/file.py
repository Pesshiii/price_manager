from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit, HTML, Button
from django.core.exceptions import ObjectDoesNotExist

from ..models import FileModel

from django.urls import reverse


class UploadFileForm(forms.ModelForm):
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
                'hx-target':'#FileInput',
                }
        self.helper.layout = Layout(
            Field('file'),
            Submit(
                name='submit', 
                value='Выбрать',
                data_bs_toggle="modal",
                data_bs_target="#SelectFileModal",)
        )

class SelectFileForm(forms.ModelForm):
    class Meta:
        model = FileModel
        fields = ("file",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        if not self.instance:
            raise ObjectDoesNotExist()
        self.helper.attrs = {
                'hx-post': reverse('dataframe:fileitem', kwargs={'pk':self.instance.pk}),
                'hx-swap':'innerHTML',
                'hx-target':'#FileInput',
                }
        self.helper.layout = Layout(
            Submit(
                name='submit', 
                value='Выбрать',
                data_bs_toggle="modal",
                data_bs_target="#SelectFileModal",)
        )

class FileInputForm(forms.ModelForm):
    sheet_name = forms.ChoiceField(label='Лист', choices=[(None, 'Выбрать лист')])
    class Meta:
        model = FileModel
        fields = ("file",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_tag=False
        if not self.instance:
            raise ObjectDoesNotExist()
        self.helper.layout = Layout(
            Field('sheet_name', css_class='form-control'),
            Button(
                    name="button",
                    value="Добавить файл",
                    hx_get=reverse("dataframe:filelist"),
                    hx_target="#SelectFileContent",
                    hx_swap="innerHTML",
                    data_bs_toggle="modal",
                    data_bs_target="#SelectFileModal",
                )
        )