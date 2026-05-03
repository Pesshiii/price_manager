from pathlib import Path

import pandas as pd
from django.http import JsonResponse
from django.db import OperationalError, ProgrammingError
from django.core.paginator import Paginator
from django.urls import reverse
from django.shortcuts import render, redirect
from django.views import View
from django.views.generic import ListView, FormView

from ..forms import FileForm, SelectFileForm
from ..models import FileModel

class FileList(ListView):
    template_name = 'dataframe/file/list.html'
    context_object_name='files'
    model = FileModel
    
class FileItem(FormView):
    template_name='dataframe/file/item.html'
    form_class = FileModel
    def get_success_url(self):
        return reverse('dataframe:filelist')
    class Meta:
        model = FileModel

class FileCreate(FormView):
    template_name='dataframe/file/create.html'
    form_class = FileModel
    def get_success_url(self):
        return reverse('dataframe:filelist')
    class Meta:
        model = FileModel