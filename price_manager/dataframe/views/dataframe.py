from pathlib import Path

import pandas as pd
from django.db import OperationalError, ProgrammingError
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, UpdateView

from core.tables import HTMXMixin

from ..forms import DataframeForm
from ..models import Dataframe, FileModel



class DataframeCreateView(CreateView):
    model = Dataframe
    form_class = DataframeForm
    template_name = 'dataframe/create.html'
    success_url = reverse_lazy('dataframe:create')


class DataframeUpdateView(UpdateView):
    model = Dataframe
    form_class = DataframeForm
    template_name = 'dataframe/update.html'
    success_url = reverse_lazy('dataframe:create')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['initial_pk'] = self.object.file_id
        return context


class DataframeTableView(HTMXMixin, TemplateView):
    template_name = 'dataframe/partials/table.html'

    def __init__(self, **kwargs):
        TemplateView.__init__(self, **kwargs)

    @staticmethod
    def _parse_index_row(index_row_raw):
        if index_row_raw in (None, ''):
            return None, None
        try:
            index_row = int(index_row_raw)
        except (TypeError, ValueError):
            return None, 'Некорректное значение index_row.'
        if index_row < 0:
            return None, 'index_row не может быть отрицательным.'
        return index_row, None

    @staticmethod
    def _read_dataframe(file_obj, sheet_name):
        extension = Path(file_obj.file.name).suffix.lower()
        with file_obj.file.open('rb') as f:
            if extension == '.csv':
                return pd.read_csv(f)
            if extension in {'.xlsx', '.xlsm', '.xls'}:
                if not sheet_name:
                    raise ValueError('Для Excel нужно указать sheet_name.')
                return pd.read_excel(f, sheet_name=sheet_name, engine='openpyxl')
        raise ValueError('Неподдерживаемый тип файла.')

    def get(self, request, *args, **kwargs):
        file_pk = request.GET.get('file_pk')
        sheet_name = request.GET.get('sheet_name', '').strip()
        index_row_raw = request.GET.get('index_row')

        context = {'columns': [], 'rows': [], 'error': None}

        if not file_pk:
            context['error'] = 'Файл не выбран.'
            return render(request, self.template_name, context)

        index_row, index_error = self._parse_index_row(index_row_raw)
        if index_error:
            context['error'] = index_error
            return render(request, self.template_name, context)

        try:
            file_obj = FileModel.objects.get(pk=file_pk)
        except (ValueError, TypeError, FileModel.DoesNotExist):
            context['error'] = 'Выбранный файл не найден.'
            return render(request, self.template_name, context)
        except (ProgrammingError, OperationalError):
            context['error'] = 'Таблица файлов недоступна. Выполните миграции.'
            return render(request, self.template_name, context)

        try:
            df = self._read_dataframe(file_obj=file_obj, sheet_name=sheet_name)
            if index_row is not None:
                if index_row >= len(df.columns):
                    raise ValueError('index_row выходит за границы количества столбцов.')
                df = df.set_index(df.columns[index_row])
            df = df.fillna('')
            context['columns'] = [str(col) for col in df.columns]
            context['rows'] = [[str(value) for value in row] for row in df.head(50).values.tolist()]
        except ValueError as exc:
            context['error'] = str(exc)
        except Exception:
            context['error'] = 'Ошибка чтения файла.'

        return render(request, self.template_name, context)
