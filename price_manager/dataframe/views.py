from django.urls import reverse
from django.views.generic import CreateView, UpdateView

from core.viewmixins import HtmxMixin

from .models import Dataframe, FileModel
from .forms import DataFrameForm

class DataframeCreate(HtmxMixin, CreateView):
    htmx_template='dataframe/create.html'
    form_class = DataFrameForm
    def form_valid(self, form):
        instance = form.save(commit=False)
        instance.file = FileModel.objects.create(file=form.cleaned_data['filefield'])
        if instance.name == '':
            instance.name = instance.file.filename
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})
    model = Dataframe

class DataframeUpdate(HtmxMixin, UpdateView):
    htmx_template='dataframe/update.html'
    form_class = DataFrameForm
    def form_valid(self, form):
        instance = form.save(commit=False)
        instance.file = FileModel.objects.create(file=form.cleaned_data['filefield'])
        if instance.name == '':
            instance.name = instance.file.filename
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})
    model = Dataframe