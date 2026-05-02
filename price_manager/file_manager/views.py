
from django.http import HttpResponse
from django.shortcuts import render
from django.views.generic import CreateView, TemplateView
from django.urls import reverse

# Импорты моделей, функций, форм, таблиц
from file_manager.models import FileModel
from .forms import *

# Обработка файлов

class FileUpload(CreateView):
  '''
  Загрузка файла <<upload/<str:name>/<int:id>/>>
  name - url name to link after
  '''
  model = FileForm
  form_class = FileForm
  template_name = 'upload/upload.html'
  def form_valid(self, form):
    f_id = form.save().id
    id = self.kwargs.get('id', 0)
    if not id==0:
      self.success_url = reverse(self.kwargs['name'],
                                kwargs={'id' : id, 'f_id':f_id})
    else:
      self.success_url = reverse(self.kwargs['name'],
                                kwargs={'f_id':f_id})
    return super().form_valid(form)


class SelectFile(TemplateView):
  template_name = 'file_manager/select_file_modal.html'

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['form'] = FileForm()
    context['files'] = FileModel.objects.order_by('-pk')
    return context

  def post(self, request, *args, **kwargs):
    selected_pk = request.POST.get('selected_file_pk')
    if selected_pk:
      return HttpResponse(selected_pk)

    form = FileForm(request.POST, request.FILES)
    if form.is_valid():
      instance = form.save()
      return HttpResponse(str(instance.pk))

    context = self.get_context_data(**kwargs)
    context['form'] = form
    return self.render_to_response(context, status=400)


def fileupload_field(request):
  return render(request, 'file_manager/fileupload_hidden_field.html', {
    'pk': request.GET.get('pk', ''),
    'name': request.GET.get('name', 'file_pk'),
  })
