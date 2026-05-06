from django.urls import reverse
from django.views.generic import CreateView, UpdateView


from ..models import Link
from ..forms import LinkForm

class LinkCreate(CreateView):
    template_name='dataframe/link/create.html'
    form_class = LinkForm
    def get_success_url(self):
        return reverse('dataframe:linkupdate', kwargs={'pk': self.object.pk})
    model = Link

class LinkUpdate(UpdateView):
    template_name='dataframe/link/update.html'
    form_class = LinkForm
    def get_success_url(self):
        return reverse('dataframe:linkupdate', kwargs={'pk': self.object.pk})
    model = Link