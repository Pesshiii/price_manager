from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, UpdateView

from dal import autocomplete
from core.viewmixins import HtmxMixin

from .models import ContentType, Dataframe, FileModel, Link, DictItem
from .forms import ContentTypeForm, DataFrameForm, LinkFormset
from .utils import read_raw_dataframe, apply_link_rules


def _resolve_unique_name(base_name, exclude_pk=None):
    """Return base_name, appending '_copy' until it is unique among Dataframe names."""
    qs = Dataframe.objects.values_list('name', flat=True)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    existing = set(qs)
    name = base_name
    while name in existing:
        name += '_copy'
    return name


class DataframeCreate(HtmxMixin, CreateView):
    htmx_template = 'dataframe/create.html'
    form_class = DataFrameForm
    model = Dataframe

    def form_valid(self, form):
        instance = form.save(commit=False)
        instance.file = FileModel.objects.create(file=form.cleaned_data['filefield'])
        if not instance.name:
            instance.name = _resolve_unique_name(instance.file.filename)
        instance.save()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})


class DataframeUpdate(HtmxMixin, UpdateView):
    htmx_template = 'dataframe/update.html'
    form_class = DataFrameForm
    model = Dataframe

    def _link_queryset(self):
        return Link.objects.filter(dataframe=self.object)

    def _file_kwargs(self):
        """Return file_pk / sheet_name for the current dataframe."""
        obj = self.object
        return {
            'file_pk': obj.file.pk if obj.file else None,
            'sheet_name': obj.sheet_name or None,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self._link_queryset()
        fk = self._file_kwargs()
        if self.request.POST:
            context['formset'] = LinkFormset(self.request.POST, queryset=qs, **fk)
        else:
            context['formset'] = LinkFormset(queryset=qs, **fk)
        return context

    def form_valid(self, form):
        qs = self._link_queryset()
        linkforms = LinkFormset(self.request.POST, queryset=qs, **self._file_kwargs())
        instance = form.save(commit=False)

        new_file = form.cleaned_data.get('filefield')
        if new_file:
            old_file = instance.file
            instance.file = FileModel.objects.create(file=new_file)
            if old_file:
                old_file.delete()

        if not instance.name:
            base = instance.file.filename if instance.file else 'dataframe'
            instance.name = _resolve_unique_name(base, exclude_pk=instance.pk)

        instance.save()

        if linkforms.is_valid():
            for link_form in linkforms:
                if link_form.cleaned_data.get('DELETE'):
                    if link_form.instance.pk:
                        link_form.instance.delete()
                    continue
                if not link_form.has_changed() and not link_form.instance.pk:
                    continue
                link = link_form.save(commit=False)
                link.dataframe = instance
                link.save()
                link.dicts.all().delete()
                DictItem.objects.bulk_create([
                    DictItem(link=link, key=d['key'], value=d['value'])
                    for d in link_form.cleaned_data.get('dictitems', [])
                    if d.get('key') or d.get('value')
                ])

        return super().form_valid(form)

    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})


class DataframeFilePreview(View):
    def get(self, request, pk):
        dataframe = get_object_or_404(Dataframe, pk=pk)
        df = read_raw_dataframe(dataframe)
        if df is None:
            return HttpResponse(
                '<p class="text-muted p-3">Файл не загружен или не может быть прочитан.</p>'
            )
        html_table = df.to_html(
            classes='table table-bordered table-sm table-hover mb-0',
            index=False,
            border=0,
            na_rep='',
        )
        return HttpResponse(f'<div class="table-responsive">{html_table}</div>')


class DataframeResultPreview(View):
    def get(self, request, pk):
        dataframe = get_object_or_404(Dataframe, pk=pk)
        df = apply_link_rules(dataframe)
        if df is None or (hasattr(df, 'empty') and df.empty):
            return HttpResponse(
                '<p class="text-muted p-3">Нет данных. Настройте привязки или выберите столбцы.</p>'
            )
        html_table = df.to_html(
            classes='table table-bordered table-sm table-hover mb-0',
            index=False,
            border=0,
            na_rep='',
        )
        return HttpResponse(f'<div class="table-responsive">{html_table}</div>')


class ContentTypeAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = ContentType.objects.order_by('name')
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs


class ContentTypeCreate(View):
    def get(self, request):
        html = render_to_string(
            'dataframe/partials/contenttype_form.html',
            {'form': ContentTypeForm()},
            request=request,
        )
        return HttpResponse(html)

    def post(self, request):
        form = ContentTypeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            return JsonResponse({'id': obj.pk, 'name': obj.name})
        html = render_to_string(
            'dataframe/partials/contenttype_form.html',
            {'form': form},
            request=request,
        )
        return HttpResponse(html, status=422)