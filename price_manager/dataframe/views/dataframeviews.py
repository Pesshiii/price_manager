from django.urls import reverse
from django.views.generic import CreateView, UpdateView


from ..models import Dataframe
from ..forms import DataFrameForm

class DataframeCreate(CreateView):
    template_name='dataframe/create.html'
    form_class = DataFrameForm
    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})
    model = Dataframe

class DataframeUpdate(UpdateView):
    template_name='dataframe/update.html'
    form_class = DataFrameForm
    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})
    model = Dataframe