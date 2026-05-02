from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from ..forms import DataframeForm
from ..models import Dataframe
from .fileupload import SelectFile, FileMetaView


class DataframeCreateView(CreateView):
    model = Dataframe
    form_class = DataframeForm
    template_name = 'dataframe/create.html'
    success_url = reverse_lazy('dataframe:create')


class DataframeUpdateView(UpdateView):
    model = Dataframe
    form_class = DataframeForm
    template_name = 'dataframe/update.html'
    success_url = reverse_lazy('dataframe:create')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['initial_pk'] = self.object.file_id
        return context
