from pathlib import Path

import pandas as pd
from django.http import JsonResponse
from django.db import OperationalError, ProgrammingError
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.views import View
from django.views.generic import ListView, FormView
from django.views.generic.edit import FormMixin
from django.contrib.auth.mixins import LoginRequiredMixin

from ..forms import FileForm, SelectFileForm
from ..models import FileModel

class FileList(LoginRequiredMixin, ListView):
    template_name = 'dataframe/file/list.html'
    model = FileModel
    context_object_name='files'
    def get(self, request, *args, **kwargs):
        # if not request.htmx:
        #     return redirect('dataframe:create')
        return super().get(request, *args, **kwargs)
    
class FileItem(LoginRequiredMixin, FormView):
    template_name='dataframe/file/item.html'
    form = SelectFileForm

class FileCreate(LoginRequiredMixin, FormView):
    template_name='dataframe/file/create.html'
    form = FileForm