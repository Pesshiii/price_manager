from django.http import JsonResponse
from django.shortcuts import render
from django.views import View

from ..forms import FileForm


class SelectFile(View):
    template_name = "dataframe/partials/file_select_modal.html"

    def get(self, request, *args, **kwargs):
        form = FileForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = FileForm(request.POST, request.FILES)
        if form.is_valid():
            file_obj = form.save()
            return JsonResponse({"pk": file_obj.pk})

        return JsonResponse({"errors": form.errors}, status=400)
