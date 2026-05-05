from django.urls import reverse
# from django.shortcuts import render, redirect
from django.views.generic import ListView, CreateView, UpdateView
import pandas as pd

from ..utils import get_sheet_names

from ..forms import UploadFileForm, SelectFileForm, FileInputForm
from ..models import FileModel

class FileList(ListView):
    template_name = 'dataframe/file/list.html'
    context_object_name='files'
    model = FileModel
    
class FileItem(UpdateView):
    template_name='dataframe/file/item.html'
    pk_url_kwarg='pk'
    form_class = SelectFileForm
    def get_success_url(self):
        return reverse('dataframe:fileswap', kwargs={'pk':self.object.pk})
    model = FileModel

class FileCreate(CreateView):
    template_name='dataframe/file/create.html'
    form_class = UploadFileForm
    def get_success_url(self):
        return reverse('dataframe:fileswap', kwargs={'pk':self.object.pk})
    model = FileModel

class FileSwappable(UpdateView):
    template_name='dataframe/file/swapable.html'
    pk_url_kwarg='pk'
    form_class = FileInputForm
    def get_form(self):
        form = super().get_form(self.form_class)
        sheet_names = get_sheet_names(self.kwargs.get('pk'))
        if not sheet_names is None:
            form.fields['sheet_name'].choices = [ (name, name)
                for name in sheet_names
            ]
        return form
    def get_success_url(self):
        return reverse('dataframe:create')
    model = FileModel