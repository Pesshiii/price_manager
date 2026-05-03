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
    model = FileModel
    context_object_name='files'
    def get(self, request, *args, **kwargs):
        # if not request.htmx:
        #     return redirect('dataframe:create')
        return super().get(request, *args, **kwargs)
    
class FileItem(FormView):
    template_name='dataframe/file/item.html'
    form = SelectFileForm
    success_url=reverse('filelist')

class FileCreate(FormView):
    template_name='dataframe/file/create.html'
    form = FileForm
    success_url=reverse('filelist')