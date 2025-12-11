from django import forms
from file_manager.models import FileModel


class FileForm(forms.ModelForm):
  class Meta:
    model = FileModel
    fields = '__all__'
  
