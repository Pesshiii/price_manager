from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from django_filters.views import FilterView

from .forms import ContentTypeForm
from .models import ContentType, Product


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


class SelectContentType(View):
    template_name = "product/partials/content_type_select_modal.html"
    paginate_by = 10

    def get(self, request, *args, **kwargs):
        page_number = request.GET.get("page", 1)
        content_types = ContentType.objects.all().order_by("pk")
        paginator = Paginator(content_types, self.paginate_by)
        page_obj = paginator.get_page(page_number)

        return render(
            request,
            self.template_name,
            {
                "page_obj": page_obj,
                "is_paginated": page_obj.has_other_pages(),
            },
        )

    def post(self, request, *args, **kwargs):
        raw_pk = request.POST.get("existing_content_type_pk")
        if not raw_pk:
            return JsonResponse(
                {"error": "Параметр existing_content_type_pk обязателен."},
                status=400,
            )

        try:
            pk = int(raw_pk)
        except (TypeError, ValueError):
            return JsonResponse(
                {"error": "existing_content_type_pk должен быть целым числом."},
                status=400,
            )

        obj = get_object_or_404(ContentType, pk=pk)
        return JsonResponse({"pk": obj.pk})
