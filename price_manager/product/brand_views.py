"""Окно «Бренды» (/brands/): покрытие, очередь несопоставленных написаний, бренды PIM, синонимы.

Первый шаг перехода на «товар = (бренд, артикул)». Логика — в
services/brands.py; здесь только экраны.

Сопоставление идёт из модалки, а ответ — фрагменты hx-swap-oob (покрытие и
очередь) плюс событие brand-mapped, которое закрывает модалку: очередь — сотни
написаний, и полная перезагрузка после каждого сбрасывала бы прокрутку и
поиск. Синонимы и слияние брендов правятся редко — там обычный
HttpResponseClientRefresh.
"""
from __future__ import annotations

from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django_htmx.http import HttpResponseClientRefresh, trigger_client_event

from product_price_manager.models import PriceManagerBrand
from supplier_product_manager.models import SupplierProduct

from .forms import brand_picker_options
from .models import Brand, BrandAlias, Product, brand_key
from .services import brands as service
from .tasks import sync_brands_task

# Сколько написаний очереди рисовать сразу; остальные — через поиск.
UNMAPPED_LIMIT = 300

TABS = ('unmapped', 'brands', 'aliases')

BRAND_MAPPED_EVENT = 'brand-mapped'


def _unmapped_context(query: str) -> dict:
    items = service.unmapped_names(query)
    return {'unmapped': items[:UNMAPPED_LIMIT], 'unmapped_total': len(items),
            'unmapped_limit': UNMAPPED_LIMIT, 'query': query}


def _brand_rows(query: str, show_inactive: bool) -> list[Brand]:
    """Бренды PIM со счётчиками: товаров, строк ПП, синонимов.

    Счётчики отдельными агрегатами, а не annotate по двум обратным связям:
    join товаров и строк ПП в одном запросе перемножил бы строки.
    """
    brands = Brand.objects.all()
    if query:
        brands = brands.filter(name__icontains=query)
    def per_brand(queryset) -> dict[int, int]:
        return dict(queryset.filter(brand__isnull=False).values_list('brand').annotate(n=Count('pk')))

    products = per_brand(Product.objects.all())
    rows = per_brand(SupplierProduct.objects.all())
    aliases = per_brand(BrandAlias.objects.all())
    rules = per_brand(PriceManagerBrand.objects.all())
    result = []
    for brand in brands.order_by('-is_active', 'name'):
        brand.products_count = products.get(brand.pk, 0)
        brand.rows_count = rows.get(brand.pk, 0)
        brand.aliases_count = aliases.get(brand.pk, 0)
        brand.rules_count = rules.get(brand.pk, 0)
        brand.in_use = any((brand.products_count, brand.rows_count, brand.aliases_count, brand.rules_count))
        if brand.is_active or show_inactive or brand.in_use:
            result.append(brand)
    return result


class BrandPage(View):
    template_name = 'product/brands.html'

    def get(self, request):
        tab = request.GET.get('tab') or 'unmapped'
        if tab not in TABS:
            tab = 'unmapped'
        query = request.GET.get('q', '').strip()
        context = {'tab': tab, 'query': query, 'coverage': service.coverage()}
        if tab == 'unmapped':
            context.update(_unmapped_context(query))
        elif tab == 'brands':
            show_inactive = request.GET.get('inactive') == '1'
            context.update(brands=_brand_rows(query, show_inactive), show_inactive=show_inactive)
        else:
            aliases = BrandAlias.objects.select_related('brand', 'created_by')
            if query:
                aliases = aliases.filter(name__icontains=query)
            brand_pk = request.GET.get('brand', '')
            if brand_pk.isdigit():
                aliases = aliases.filter(brand_id=int(brand_pk))
            context['aliases'] = aliases
        return render(request, self.template_name, context)


class BrandMapView(View):
    """Сопоставить одно написание: с брендом PIM, «игнорировать» или создать бренд в PIM."""

    template_name = 'product/partials/brand_map.html'
    response_template = 'product/partials/brand_mapped_response.html'

    def _context(self, name: str, query: str, **extra) -> dict:
        item = service.unmapped_name(name)
        return {
            'item': item,
            'query': query,
            'suggestions': service.suggest(name, service.suggestion_keys()),
            'same_key': service.same_key_brands(name) if item.ambiguous else [],
            'brand_options': brand_picker_options(set(), active_only=True),
            **extra,
        }

    def get(self, request):
        name = request.GET.get('name', '')
        return render(request, self.template_name, self._context(name, request.GET.get('q', '')))

    def post(self, request):
        name = request.POST.get('name', '')
        query = request.POST.get('q', '')
        action = request.POST.get('action')
        try:
            if action == 'map':
                # Кнопка-подсказка («Похоже на: …») приходит как suggested и сильнее
                # бренда, отмеченного в списке.
                brand_pk = request.POST.get('suggested') or request.POST.get('brand') or None
                brand = Brand.objects.filter(pk=brand_pk, is_active=True).first()
                if brand is None:
                    return render(request, self.template_name,
                                  self._context(name, query, error='Выберите бренд PIM'))
                service.add_alias(name, brand, request.user)
                messages.success(request, f'«{name}» → {brand.name}')
            elif action == 'ignore':
                service.add_alias(name, None, request.user)
                messages.success(request, f'«{name}» — без бренда')
            elif action == 'create':
                brand, created = service.create_pim_brand(request.POST.get('new_name') or name)
                if brand_key(brand.name) != brand_key(name):
                    service.add_alias(name, brand, request.user)
                messages.success(request, f'Бренд «{brand.name}» {"создан" if created else "уже был"} в PIM, '
                                          f'«{name}» сопоставлен с ним')
            else:
                return render(request, self.template_name, self._context(name, query, error='Неизвестное действие'))
        except (service.PimBrandError, ValueError) as exc:
            return render(request, self.template_name, self._context(name, query, error=str(exc)))
        response = render(request, self.response_template,
                          {'coverage': service.coverage(), **_unmapped_context(query)})
        return trigger_client_event(response, BRAND_MAPPED_EVENT)


class BrandSyncView(View):
    """«Обновить из PIM»: список брендов и пересопоставление — в фоне."""

    def post(self, request):
        sync_brands_task.delay()
        messages.info(request, 'Список брендов обновляется из PIM — через минуту обновите страницу')
        tab = request.POST.get('tab')
        return redirect(f"{reverse('brands')}?tab={tab if tab in TABS else 'unmapped'}")


class BrandAliasUpdateView(View):
    """Правка синонима: другой бренд, «игнорировать» или удалить."""

    template_name = 'product/partials/brand_alias_form.html'

    def _render(self, request, alias, error=''):
        selected = {str(alias.brand_id)} if alias.brand_id else set()
        return render(request, self.template_name, {
            'alias': alias, 'error': error,
            'brand_options': brand_picker_options(selected, active_only=True),
        })

    def get(self, request, pk):
        return self._render(request, get_object_or_404(BrandAlias, pk=pk))

    def post(self, request, pk):
        alias = get_object_or_404(BrandAlias, pk=pk)
        if request.POST.get('delete') == 'true':
            service.delete_alias(alias)
            messages.success(request, f'Синоним «{alias.name}» удалён — его строки вернулись в очередь')
            return HttpResponseClientRefresh()
        if request.POST.get('ignore') == 'true':
            brand = None
        else:
            brand = Brand.objects.filter(pk=request.POST.get('brand') or None, is_active=True).first()
            if brand is None:
                return self._render(request, alias, error='Выберите бренд PIM или «Без бренда»')
        service.add_alias(alias.name, brand, request.user)
        messages.success(request, f'«{alias.name}» → {brand.name if brand else "без бренда"}')
        return HttpResponseClientRefresh()


class BrandMergeView(View):
    """«Перенести в…»: всё с бренда, которого больше нет в PIM, — на живой бренд."""

    template_name = 'product/partials/brand_merge.html'

    def _render(self, request, brand, error=''):
        return render(request, self.template_name, {
            'brand': brand, 'error': error,
            'brand_options': brand_picker_options(set(), active_only=True),
        })

    def get(self, request, pk):
        return self._render(request, get_object_or_404(Brand, pk=pk, is_active=False))

    def post(self, request, pk):
        loser = get_object_or_404(Brand, pk=pk, is_active=False)
        winner = Brand.objects.filter(pk=request.POST.get('brand') or None, is_active=True).first()
        if winner is None:
            return self._render(request, loser, error='Выберите бренд, на который перенести')
        service.merge_brands(loser, winner)
        messages.success(request, f'Всё с бренда «{loser.name}» перенесено на «{winner.name}»')
        return HttpResponseClientRefresh()
