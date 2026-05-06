from django.urls import reverse
from django.views.generic import ListView, CreateView, RedirectView

from ..forms import FileForm
from ..models import FileModel, Dataframe

class FileList(ListView):
    template_name = 'dataframe/file/list.html'
    context_object_name='files'
    model = FileModel

class FileCreate(CreateView):
    template_name='dataframe/file/create.html'
    form_class = FileForm
    def get_success_url(self):
        dfs = Dataframe.objects.all()
        name = self.object.filename
        if not dfs.filter(name=f'{name}').exists():
            df = Dataframe.objects.create(name=name, file=self.object)
        else:
            i = 1
            while dfs.filter(name=f'{name}{i}').exists():
                i+=1
            df = Dataframe.objects.create(name=f'{name}{i}', file=self.object)
        return reverse('dataframe:update', kwargs={'pk':df.pk})
    model = FileModel

class FileSelect(RedirectView):
    pk_url_kwarg="pk"
    def get_redirect_url(self, *args, **kwargs):
        pk = kwargs.pop('pk', None)
        file = FileModel.objects.get(pk=pk)
        dfs = Dataframe.objects.all()
        if not file.file:
            file.delete()
            return reverse('dataframe:filecreate')
        name = file.filename
        if not dfs.filter(name=f'{name}').exists():
            df = Dataframe.objects.create(name=name, file=file)
        else:
            i = 1
            while dfs.filter(name=f'{name}{i}').exists():
                i+=1
            df = Dataframe.objects.create(name=f'{name}{i}', file=file)
        return reverse('dataframe:update', kwargs={'pk':df.pk})