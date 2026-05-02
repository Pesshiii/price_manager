from django.http import JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views import View

from ..forms import FileForm
from ..models import FileModel


class SelectFile(View):
    template_name = "dataframe/partials/file_select_modal.html"
    per_page = 10

    @staticmethod
    def _success_response(file_obj):
        return JsonResponse({"pk": file_obj.pk})

    def get(self, request, *args, **kwargs):
        form = FileForm()
        files_queryset = FileModel.objects.order_by("-id")
        paginator = Paginator(files_queryset, self.per_page)
        page_obj = paginator.get_page(request.GET.get("page"))
        context = {
            "form": form,
            "page_obj": page_obj,
            "files": page_obj.object_list,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        existing_file_pk = request.POST.get("existing_file_pk")
        if existing_file_pk:
            try:
                file_obj = FileModel.objects.get(pk=existing_file_pk)
            except (ValueError, TypeError):
                return JsonResponse({"errors": {"existing_file_pk": ["Некорректный идентификатор файла."]}}, status=400)
            except FileModel.DoesNotExist:
                return JsonResponse({"errors": {"existing_file_pk": ["Файл не найден."]}}, status=404)

            return self._success_response(file_obj)

        form = FileForm(request.POST, request.FILES)
        if form.is_valid():
            file_obj = form.save()
            return self._success_response(file_obj)

        return JsonResponse({"errors": form.errors}, status=400)
