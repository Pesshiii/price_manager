from pathlib import Path

import pandas as pd
from django.http import JsonResponse
from django.db import OperationalError, ProgrammingError
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views import View

from ..forms import FileForm
from ..models import FileModel


class SelectFile(View):
    template_name = "dataframe/partials/file_select_modal.html"
    per_page = 10

    @staticmethod
    def _success_response(request, file_obj):
        if request.headers.get("HX-Request") == "true":
            field_name = request.POST.get("field_name") or "file_pk"
            return render(request, "dataframe/partials/file_select_success.html", {"pk": file_obj.pk, "field_name": field_name})
        return JsonResponse({"pk": file_obj.pk})


    def _build_modal_context(self, form, page):
        try:
            files_queryset = FileModel.objects.order_by("-id")
            paginator = Paginator(files_queryset, self.per_page)
            page_obj = paginator.get_page(page)
            files = page_obj.object_list
        except (ProgrammingError, OperationalError):
            page_obj = Paginator([], self.per_page).get_page(1)
            files = page_obj.object_list

        return {"form": form, "page_obj": page_obj, "files": files}

    def get(self, request, *args, **kwargs):
        form = FileForm()
        context = self._build_modal_context(form=form, page=request.GET.get("page"))
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
            except (ProgrammingError, OperationalError):
                return JsonResponse({"errors": {"database": ["Таблица файлов отсутствует. Выполните миграции."]}}, status=503)

            return self._success_response(request, file_obj)

        form = FileForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                file_obj = form.save()
            except (ProgrammingError, OperationalError):
                return JsonResponse({"errors": {"database": ["Таблица файлов отсутствует. Выполните миграции."]}}, status=503)
            return self._success_response(request, file_obj)

        if request.headers.get("HX-Request") == "true":
            context = self._build_modal_context(form=form, page=request.GET.get("page"))
            return render(request, self.template_name, context, status=400)

        return JsonResponse({"errors": form.errors}, status=400)


class FileMetaView(View):
    @staticmethod
    def _build_sheet_names(file_obj):
        extension = Path(file_obj.file.name).suffix.lower()

        if extension == ".csv":
            return ["CSV"]

        if extension in {".xlsx", ".xlsm", ".xls"}:
            with file_obj.file.open("rb") as f:
                excel_file = pd.ExcelFile(f, engine="openpyxl")
                return excel_file.sheet_names

        return []

    def get(self, request, pk, *args, **kwargs):
        try:
            file_obj = FileModel.objects.get(pk=pk)
        except FileModel.DoesNotExist:
            return JsonResponse({"error": "Файл не найден."}, status=404)
        except (ProgrammingError, OperationalError):
            return JsonResponse({"error": "Таблица файлов отсутствует. Выполните миграции."}, status=503)

        try:
            sheets = self._build_sheet_names(file_obj)
        except Exception:
            return JsonResponse({"error": "Не удалось получить метаданные файла."}, status=400)

        filename = Path(file_obj.file.name).stem
        return JsonResponse({"filename": filename, "sheets": sheets})
