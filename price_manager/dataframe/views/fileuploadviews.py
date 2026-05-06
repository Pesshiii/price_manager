from django.urls import reverse
# from django.shortcuts import render, redirect
from django.views.generic import ListView, CreateView, DetailView
import pandas as pd

from ..utils import get_sheet_names

from ..forms import UploadFileForm, SelectFileForm
from ..models import FileModel, Dataframe

class FileList(ListView):
    template_name = 'dataframe/file/list.html'
    context_object_name='files'
    model = FileModel

class FileCreate(CreateView):
    template_name='dataframe/file/create.html'
    form_class = UploadFileForm
    def get_success_url(self):
        dfs = Dataframe.objects.all()
        name = self.object.filename
        if not dfs.filter(name=f'{name}').exists:
            df = Dataframe.objects.create(name=name, file=self.object)
        else:
            i = 1
            while dfs.filter(name=f'{name}{i}').exists:
                i+=1
            df = Dataframe.objects.create(name=f'{name}{i}', file=self.object)
        return reverse('dataframe:update', kwargs={'pk':df.pk})
    model = FileModel

class FileSelect(DetailView):
    template_name='dataframe/file/create.html'
    pk_url_kwarg="pk"
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dfs = Dataframe.objects.all()
        if not self.object.file:
            self.object.delete()
            return context
        name = self.object.filename
        if not dfs.filter(name=f'{name}').exists:
            df = Dataframe.objects.create(name=name, file=self.object)
        else:
            i = 1
            while dfs.filter(name=f'{name}{i}').exists:
                i+=1
            df = Dataframe.objects.create(name=f'{name}{i}', file=self.object)
        if df:
            context['pk']=df.pk
        return context
    model = FileModel