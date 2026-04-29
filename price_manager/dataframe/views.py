from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseNotAllowed
from django.urls import reverse
from django.views.generic import CreateView, UpdateView

from .forms import Form
from .models import Dataframe, FileModel



class Create(LoginRequiredMixin, CreateView):
    model = Dataframe
    form_class = Form
    template_name = "dataframe/create.html"

    def form_valid(self, form):
        messages.success(self.request, "Датафрейм создан.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("dtaframe:update", kwargs={"slug": self.object.slug})


class Update(LoginRequiredMixin, UpdateView):
    model = Dataframe
    form_class = Form
    template_name = "dataframe/update.html"
    slug_url_kwarg = "slug"

    def form_valid(self, form):
        messages.success(self.request, "Датафрейм обновлен.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("dtaframe:update", kwargs={"slug": self.object.slug})



def jsonform_file_handler(request):
    if request.method == "GET":
        files = [
            {"value": item.file.url, "name": item.file.name.split("/")[-1]}
            for item in FileModel.objects.all().order_by("-id")
        ]
        return JsonResponse(files, safe=False)

    if request.method == "POST":
        uploaded = request.FILES.get("file")
        if not uploaded:
            return JsonResponse({"error": "file is required"}, status=400)

        item = FileModel.objects.create(file=uploaded)
        return JsonResponse({"value": item.file.url, "name": item.file.name.split("/")[-1]})

    if request.method == "DELETE":
        file_url = request.GET.get("value")
        if not file_url:
            return JsonResponse({"error": "value is required"}, status=400)

        item = FileModel.objects.filter(file=file_url.lstrip("/")).first()
        if item:
            item.file.delete(save=False)
            item.delete()
        return JsonResponse({"success": True})

    return HttpResponseNotAllowed(["GET", "POST", "DELETE"])
