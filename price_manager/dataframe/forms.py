from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, HTML

from .models import FileModel, Dataframe


class FileForm(forms.ModelForm):
    class Meta:
        model = FileModel
        fields = ("file",)


class DataframeForm(forms.ModelForm):
    file_pk = forms.IntegerField(required=True, widget=forms.HiddenInput)
    sheet_name = forms.ChoiceField(choices=())

    class Meta:
        model = Dataframe
        fields = ("name", "sheet_name", "index_row")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["sheet_name"].choices = [("", "---------")]
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
