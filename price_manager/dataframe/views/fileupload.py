from pathlib import Path

import pandas as pd
from django.http import JsonResponse
from django.db import OperationalError, ProgrammingError
from django.core.paginator import Paginator
from django.urls import reverse
from django.shortcuts import render, redirect
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, TemplateView

from ..forms import FileForm, SelectFileForm, FileInput
from ..models import FileModel

class FileList(ListView):
    template_name = 'dataframe/file/list.html'
    context_object_name='files'
    model = FileModel
    
class FileItem(UpdateView):
    template_name='dataframe/file/item.html'
    pk_url_kwarg='pk'
    form_class = SelectFileForm
    def form_valid(self, form):
        self.instance = form.save()
        return super().form_valid(form)
    def get_success_url(self):
        return reverse('dataframe:fileswap', kwargs={'pk':self.instance.pk})
    model = FileModel

class FileCreate(CreateView):
    template_name='dataframe/file/create.html'
    form_class = FileForm
    def form_valid(self, form):
        self.instance = form.save()
        return super().form_valid(form)
    def get_success_url(self):
        return reverse('dataframe:fileswap', kwargs={'pk':self.instance.pk})
    model = FileModel

class FileSwappable(UpdateView):
    template_name='dataframe/file/swapable.html'
    pk_url_kwarg='pk'
    form_class = FileInput
    def get_success_url(self):
        return reverse('dataframe:create')
    model = FileModel