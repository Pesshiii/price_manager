from django.urls import reverse
from django.views.generic import CreateView, UpdateView

from core.viewmixins import HtmxMixin

from .models import Dataframe, FileModel, Link, DictItem
from .forms import DataFrameForm, LinkFormset

class DataframeCreate(HtmxMixin, CreateView):
    htmx_template='dataframe/create.html'
    form_class = DataFrameForm
    def form_valid(self, form):
        instance = form.save(commit=False)
        instance.file = FileModel.objects.create(file=form.cleaned_data['filefield'])
        if instance.name == '':
            name = instance.file.filename
            names = Dataframe.objects.all().values_list('name', flat=True)
            while name in names:
                name += '_copy'
            instance.name = name
        instance.save()
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})
    model = Dataframe

class DataframeUpdate(HtmxMixin, UpdateView):
    htmx_template='dataframe/update.html'
    form_class = DataFrameForm
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context["formset"] = LinkFormset(self.request.POST)
        else:
            context["formset"] = LinkFormset(queryset=Link.objects.filter(dataframe=self.object))
        return context
    def form_valid(self, form):
        linkforms = LinkFormset(self.request.POST)
        instance = form.save(commit=False)
        instance.file = FileModel.objects.create(file=form.cleaned_data['filefield'])
        if instance.name == '':
            name = instance.file.filename
            names = Dataframe.objects.all().values_list('name', flat=True)
            while name in names:
                name += '_copy'
            instance.name = name
        instance.save()
        if linkforms.is_valid():
            for form in linkforms:
                link = form.save(commit=False)
                link.dataframe = instance
                link.save()
                for dictobj in form.cleaned_data['dictitems']:
                    DictItem.objects.get_or_create(link=link, key=dictobj['key'], value=dictobj['value'])
        return super().form_valid(form)
    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})
    model = Dataframe