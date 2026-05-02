
from django import forms
from django.http import HttpResponse
from django.views.generic import CreateView, TemplateView
from django.urls import reverse

# Импорты моделей, функций, форм, таблиц
from file_manager.models import FileModel
from .forms import *


class SelectExistingFileForm(forms.Form):
  file_id = forms.ModelChoiceField(
      queryset=FileModel.objects.all().order_by('-id'),
      label='Уже загруженный файл'
  )

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
    context['upload_form'] = FileForm()
    context['existing_form'] = SelectExistingFileForm()
    return context

  def post(self, request, *args, **kwargs):
    action = request.POST.get('action')
    if action == 'upload':
      form = FileForm(request.POST, request.FILES)
      if form.is_valid():
        file_instance = form.save()
        return HttpResponse(str(file_instance.pk))
    elif action == 'select':
      form = SelectExistingFileForm(request.POST)
      if form.is_valid():
        file_instance = form.cleaned_data['file_id']
        return HttpResponse(str(file_instance.pk))

    context = self.get_context_data()
    context['upload_form'] = form if action == 'upload' else FileForm()
    context['existing_form'] = form if action == 'select' else SelectExistingFileForm()
    return self.render_to_response(context, status=400)
