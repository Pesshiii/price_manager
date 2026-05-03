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
                'hx-post': reverse('filecreate'),
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
                'hx-post': reverse('filesselect', kwargs={'pk':self.instance.pk}),
                'hx-swap':'innerHTML',
                'hx-target':'#SelectFile .modal-body',
                }
        self.helper.layout = Layout(
            Field('pk'),
            Submit(value='Выбрать')
        )


class DataframeForm(forms.ModelForm):
    file_pk = forms.IntegerField(required=True, widget=forms.HiddenInput)
    sheet_name = forms.ChoiceField(choices=())

    class Meta:
        model = Dataframe
        fields = ("name", "sheet_name", "index_row")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Div(
                Field("name"),
                css_class="mb-3",
            ),
            Div(
                Field("sheet_name", css_class="form-select dataframe-sheet-select"),
                css_class="mb-3",
            ),
            Div(
                Field("index_row"),
                css_class="mb-3",
            ),
        )

        self.fields["sheet_name"].choices = [("", "Не выбран")]
        if self.instance and self.instance.pk and self.instance.sheet_name:
            self.fields["sheet_name"].choices.append((self.instance.sheet_name, self.instance.sheet_name))

        if self.instance and self.instance.pk and self.instance.file_id:
            self.fields["file_pk"].initial = self.instance.file_id

    def clean_file_pk(self):
        file_pk = self.cleaned_data["file_pk"]
        if not FileModel.objects.filter(pk=file_pk).exists():
            raise forms.ValidationError("Выбранный файл не найден.")
        return file_pk

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.file_id = self.cleaned_data["file_pk"]
        if commit:
            instance.save()
        return instance
