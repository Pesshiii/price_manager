from django.urls import reverse
from django.views.generic import CreateView

from file_manager.forms import FileForm
from file_manager.models import FileModel


class FileUpload(CreateView):
    model = FileModel
    form_class = FileForm
    template_name = 'upload/upload.html'

    def form_valid(self, form):
        f_id = form.save().id
        supplier_id = self.kwargs.get('id', 0)
        if supplier_id:
            self.success_url = reverse(self.kwargs['name'], kwargs={'id': supplier_id, 'f_id': f_id})
        else:
            self.success_url = reverse(self.kwargs['name'], kwargs={'f_id': f_id})
        return super().form_valid(form)
