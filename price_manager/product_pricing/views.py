from django.contrib import messages
from django.db.models import Count, ProtectedError
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, TemplateView, UpdateView, View
from django_htmx.http import HttpResponseClientRefresh

from core.models import TaskRunHistory

from .forms import ProductPriceRuleForm, ProductPriceTypeForm
from .models import ProductPriceRule, ProductPriceType
from .tables import ProductPriceRuleTable, ProductPriceTypeTable
from .tasks import update_product_prices_task

UPDATE_TASK_NAME = 'product_pricing.update_product_prices'


class ProductPricingPage(TemplateView):
    """«Цены товаров»: типы расчётных цен и наценки на товар."""

    template_name = 'product_pricing/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # order_by явно: Meta.ordering к запросам с агрегацией Django не применяет.
        types = (ProductPriceType.objects.annotate(prices_count=Count('prices'))
                 .order_by(*ProductPriceType._meta.ordering))
        rules = (ProductPriceRule.objects.select_related('price_type')
                 .prefetch_related('categories', 'brands')
                 .annotate(prices_count=Count('prices'))
                 .order_by(*ProductPriceRule._meta.ordering))
        context['types_table'] = ProductPriceTypeTable(types)
        context['rules_table'] = ProductPriceRuleTable(rules)
        context['has_types'] = types.exists()
        context['last_run'] = TaskRunHistory.objects.filter(task_name=UPDATE_TASK_NAME).order_by('-pk').first()
        return context


class ProductPricesRecalculate(View):
    """Пересчитать сейчас, не дожидаясь расписания."""

    def post(self, request, *args, **kwargs):
        update_product_prices_task.delay()
        messages.success(request, 'Пересчёт цен товаров запущен')
        return redirect(reverse('product-pricing'))


class _ModalFormMixin:
    success_message = 'Сохранено'

    def form_valid(self, form):
        form.save()
        messages.success(self.request, self.success_message)
        return HttpResponseClientRefresh()

    def get_success_url(self):
        return reverse('product-pricing')


class _ModalDeleteMixin:
    delete_message = 'Удалено'
    protected_message = ''

    def post(self, request, *args, **kwargs):
        if request.POST.get('delete') == 'true':
            try:
                self.get_object().delete()
                messages.success(request, self.delete_message)
            except ProtectedError:
                messages.error(request, self.protected_message)
            return HttpResponseClientRefresh()
        return super().post(request, *args, **kwargs)


class ProductPriceTypeCreate(_ModalFormMixin, CreateView):
    model = ProductPriceType
    form_class = ProductPriceTypeForm
    template_name = 'product_pricing/partials/modal_form.html'
    extra_context = {'title': 'Новый тип цены'}
    success_message = 'Тип цены добавлен'


class ProductPriceTypeUpdate(_ModalDeleteMixin, _ModalFormMixin, UpdateView):
    model = ProductPriceType
    form_class = ProductPriceTypeForm
    template_name = 'product_pricing/partials/modal_form.html'
    extra_context = {'title': 'Тип цены', 'can_delete': True,
                     'delete_confirm': 'Удалить тип цены вместе с его расчётными ценами?'}
    delete_message = 'Тип цены удалён'
    protected_message = 'У этого типа цены есть наценки — сначала удалите их'


class ProductPriceRuleCreate(_ModalFormMixin, CreateView):
    model = ProductPriceRule
    form_class = ProductPriceRuleForm
    template_name = 'product_pricing/partials/modal_form.html'
    extra_context = {'title': 'Новая наценка на товар'}
    success_message = 'Наценка добавлена — цены пересчитаются при следующем пересчёте'


class ProductPriceRuleUpdate(_ModalDeleteMixin, _ModalFormMixin, UpdateView):
    model = ProductPriceRule
    form_class = ProductPriceRuleForm
    template_name = 'product_pricing/partials/modal_form.html'
    extra_context = {'title': 'Наценка на товар', 'can_delete': True,
                     'delete_confirm': 'Удалить наценку? Её цены исчезнут при следующем пересчёте.'}
    success_message = 'Наценка сохранена — цены пересчитаются при следующем пересчёте'
    delete_message = 'Наценка удалена'
