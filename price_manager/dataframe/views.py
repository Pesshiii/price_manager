from __future__ import annotations

import io
import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from .forms import ConvertForm, DataframeForm, PreviewUploadForm
from .models import Dataframe
from .registry import READERS, TRANSFORMS
from .services import apply, apply_partial


def _registry_context():
    return {
        'readers': [
            {
                'name': r.name, 'label': r.label, 'extensions': list(r.extensions),
                'args': [a.__dict__ for a in r.args],
            }
            for r in READERS.values()
        ],
        'transforms': [
            {
                'name': t.name, 'label': t.label,
                'args': [a.__dict__ for a in t.args],
            }
            for t in TRANSFORMS.values()
        ],
    }


class DataframeListView(LoginRequiredMixin, ListView):
    model = Dataframe
    template_name = 'dataframe/list.html'
    context_object_name = 'dataframes'


class DataframeCreateView(LoginRequiredMixin, CreateView):
    model = Dataframe
    form_class = DataframeForm
    template_name = 'dataframe/edit.html'

    def get_success_url(self):
        return reverse('dataframe:edit', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['registry_json'] = json.dumps(_registry_context(), ensure_ascii=False)
        ctx['instructions_json'] = json.dumps(
            getattr(self.object, 'instructions', None) or {
                'reader': {'func': '', 'args': {}}, 'transforms': []
            },
            ensure_ascii=False,
        )
        return ctx


class DataframeUpdateView(LoginRequiredMixin, UpdateView):
    model = Dataframe
    form_class = DataframeForm
    template_name = 'dataframe/edit.html'

    def get_success_url(self):
        return reverse('dataframe:edit', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['registry_json'] = json.dumps(_registry_context(), ensure_ascii=False)
        ctx['instructions_json'] = json.dumps(
            self.object.instructions or {'reader': {'func': '', 'args': {}}, 'transforms': []},
            ensure_ascii=False,
        )
        return ctx


class DataframeDeleteView(LoginRequiredMixin, DeleteView):
    model = Dataframe
    template_name = 'dataframe/confirm_delete.html'
    success_url = reverse_lazy('dataframe:list')


class DataframeModalCreateView(LoginRequiredMixin, View):
    """HTMX endpoint returning the create form as a modal fragment.

    POST returns 204 with HX-Trigger=dataframe:created carrying the new pk,
    so any parent page can react and update its selects.
    """

    def get(self, request):
        form = DataframeForm()
        return render(request, 'dataframe/partials/_modal_create.html', {
            'form': form,
            'registry_json': json.dumps(_registry_context(), ensure_ascii=False),
            'instructions_json': json.dumps(
                {'reader': {'func': '', 'args': {}}, 'transforms': []}, ensure_ascii=False
            ),
        })

    def post(self, request):
        form = DataframeForm(request.POST)
        if not form.is_valid():
            return render(request, 'dataframe/partials/_modal_create.html', {
                'form': form,
                'registry_json': json.dumps(_registry_context(), ensure_ascii=False),
                'instructions_json': request.POST.get('instructions_json') or '{}',
            }, status=400)
        obj = form.save()
        response = HttpResponse(status=204)
        response['HX-Trigger'] = json.dumps({
            'dataframe:created': {'pk': obj.pk, 'name': obj.name}
        })
        return response


class PreviewView(LoginRequiredMixin, View):
    """Run an ephemeral pipeline (defined by POSTed JSON) against the uploaded
    file and return an HTML preview of the first 50 rows. Up_to limits the
    number of transforms applied.
    """

    def post(self, request):
        form = PreviewUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return HttpResponseBadRequest('Файл обязателен')
        try:
            instructions = json.loads(request.POST.get('instructions') or '{}')
        except json.JSONDecodeError as e:
            return HttpResponseBadRequest(f'Невалидный JSON: {e}')
        up_to_raw = request.POST.get('up_to')
        up_to = int(up_to_raw) if up_to_raw not in (None, '') else None

        ephemeral = Dataframe(name='__preview__', instructions=instructions)
        try:
            df = apply_partial(ephemeral, form.cleaned_data['file'], up_to=up_to)
        except Exception as e:
            return render(request, 'dataframe/partials/_preview_error.html', {'error': str(e)})
        head = df.head(50)
        return render(request, 'dataframe/partials/_preview_table.html', {
            'table_html': head.to_html(classes='table table-sm table-striped table-bordered',
                                       index=False, border=0),
            'rows_total': len(df),
            'cols_total': len(df.columns),
        })


class ConvertToCsvView(LoginRequiredMixin, View):
    def post(self, request, pk):
        df_obj = get_object_or_404(Dataframe, pk=pk)
        if 'file' not in request.FILES:
            return HttpResponseBadRequest('Файл обязателен')
        try:
            result = apply(df_obj, request.FILES['file'])
        except Exception as e:
            return HttpResponse(f'Ошибка обработки: {e}', status=400, content_type='text/plain; charset=utf-8')
        buf = io.StringIO()
        result.to_csv(buf, index=False)
        response = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
        filename = f'{df_obj.name}.csv'.replace('"', '')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class DemoView(LoginRequiredMixin, TemplateView):
    template_name = 'dataframe/demo.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form'] = ConvertForm()
        return ctx
