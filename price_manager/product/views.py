from django.http import JsonResponse
from django.shortcuts import render
from django.views import View

from django_filters.views import FilterView

from .forms import ContentTypeForm
from .models import Product


class CreateContentType(View):
    template_name = "product/partials/content_type_create_modal.html"

    def get(self, request, *args, **kwargs):
        form = ContentTypeForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = ContentTypeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            return JsonResponse({"pk": obj.pk})

        return JsonResponse({"errors": form.errors}, status=400)
