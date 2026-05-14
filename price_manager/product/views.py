import math

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView
from django_filters.views import FilterView

from .filters import ProductFilter
from .models import Content, Product
from dataframe.forms import DataFrameForm
from dataframe.models import ContentType, Dataframe
from dataframe.utils import apply_link_rules
from dataframe.views import DataframeUpdate


def _coerce(v):
    if hasattr(v, 'item'):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


class ProductListView(FilterView):
    model = Product
    filterset_class = ProductFilter
    template_name = 'product/list.html'
    paginate_by = 24

    def get_queryset(self):
        return (
            Product.objects
            .select_related('category')
            .prefetch_related('prices__ptype', 'stocks__stype')
            .order_by('name')
        )

    def get_template_names(self):
        if self.request.htmx:
            return ['product/partials/cards.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter'] = self.filterset
        return context


class ProductDetailView(DetailView):
    model = Product
    template_name = 'product/detail.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return (
            Product.objects
            .select_related('category')
            .prefetch_related(
                'prices__ptype',
                'stocks__stype',
                'content',
            )
        )


class ProductImportDataFrameForm(DataFrameForm):
    @property
    def helper(self):
        h = super().helper
        if self.instance.pk:
            h.attrs['hx-post'] = reverse('product:product-import', kwargs={'pk': self.instance.pk})
        return h


class ProductImportSelectView(ListView):
    model = Dataframe
    template_name = 'product/import_select.html'
    context_object_name = 'dataframes'
    ordering = ['name']


class ProductImportView(DataframeUpdate):
    htmx_template = 'product/import.html'
    form_class = ProductImportDataFrameForm

    def get_success_url(self):
        return reverse('product:product-import', kwargs={'pk': self.object.pk}) + '?saved=1'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['content_types'] = ContentType.objects.filter(
            link__dataframe=self.object
        ).order_by('name')
        return context


class ProductImportExecuteView(View):
    def post(self, request, pk):
        dataframe = get_object_or_404(Dataframe, pk=pk)
        redirect_url = reverse('product:product-import', kwargs={'pk': pk})

        df = apply_link_rules(dataframe)
        if df is None:
            messages.error(request, 'Нет данных для импорта. Настройте привязки и убедитесь, что файл загружен.')
            return HttpResponseRedirect(redirect_url)

        name_field = request.POST.get('name_field', '').strip()
        if not name_field:
            messages.error(request, 'Выберите поле для имени товара.')
            return HttpResponseRedirect(redirect_url)

        if name_field not in df.columns:
            messages.error(
                request,
                f'Поле «{name_field}» не найдено в результате привязок. '
                f'Доступные поля: {", ".join(df.columns)}.'
            )
            return HttpResponseRedirect(redirect_url)

        create_new = request.POST.get('create_new') == 'on'
        created = updated = skipped = 0

        for _, row in df.iterrows():
            raw = row.get(name_field)
            name = str(raw).strip() if raw is not None else ''
            if not name or name == 'nan':
                skipped += 1
                continue

            if create_new:
                product, was_new = Product.objects.get_or_create(name=name)
            else:
                try:
                    product = Product.objects.get(name=name)
                    was_new = False
                except Product.DoesNotExist:
                    skipped += 1
                    continue

            row_dict = {k: _coerce(v) for k, v in row.to_dict().items()}
            _, content_new = Content.objects.update_or_create(
                product=product,
                defaults={'content': row_dict},
            )

            if was_new or content_new:
                created += 1
            else:
                updated += 1

        messages.success(
            request,
            f'Импорт завершён: создано — {created}, обновлено — {updated}, пропущено строк — {skipped}.',
        )
        return HttpResponseRedirect(redirect_url)
