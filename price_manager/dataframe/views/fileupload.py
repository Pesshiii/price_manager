from django.urls import reverse
# from django.shortcuts import render, redirect
from django.views.generic import ListView, CreateView, UpdateView

from ..utils import get_sheet_names

from ..forms import FileForm, SelectFileForm, FileInputForm
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
    form_class = FileInputForm
    def get_form(self, form_class = ...):
        form = super().get_form(form_class)
        form.fields['sheet_name'].choices = [ (name, name)
            for name in get_sheet_names(self.instance.pk)
        ]
        return form
    def get_success_url(self):
        return reverse('dataframe:create')
    model = FileModel