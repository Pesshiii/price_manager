from django.urls import reverse
from django.views.generic import ListView, CreateView, RedirectView

from ..forms import ContentTypeForm
from ..models import ContentType, Link, Dataframe

class ContentTypeList(ListView):
    template_name = 'product/content/list.html'
    context_object_name='contenttypes'
    model = ContentType
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["df_pk"] = self.kwargs.get('df_pk', None)
        return context
    

class ContentTypeCreate(CreateView):
    template_name='product/content/create.html'
    form_class = ContentTypeForm
    model = ContentType
    def get_success_url(self):
        return reverse('dataframe:contentypeselect', kwargs={'pk': self.object.pk})

class ContentTypeSelect(RedirectView):
    pk_url_kwarg="pk"
    def get_redirect_url(self, *args, **kwargs):
        df_pk = kwargs.pop('df_pk', None)
        pk = kwargs.pop('pk', None)
        content_type = ContentType.objects.get(pk=pk)
        link = Link.objects.create(contenttype=content_type, dataframe=df_pk)
        return reverse('dataframe:linkupdate', kwargs={'df_pk':df_pk, 'pk':link.pk})