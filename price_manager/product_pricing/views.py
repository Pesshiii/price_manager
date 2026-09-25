from django.contrib import messages
from django.db.models import Count, ProtectedError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import CreateView, TemplateView, UpdateView, View
from django_htmx.http import HttpResponseClientRefresh

from core.models import TaskRunHistory
from core.task_runner import dispatch_after_commit

from .forms import ProductPriceRuleForm, ProductPriceTypeForm
from .models import ProductPriceRule, ProductPriceType
from .tables import ProductPriceRuleTable, ProductPriceTypeTable
from .services import preview_rule
from .tasks import update_product_prices_task

UPDATE_TASK_NAME = 'product_pricing.update_product_prices'
# Приоритет наценки, заведённой с карточки товара: важнее общих (100).
PRODUCT_RULE_PRIORITY = 10


class ProductPricingPage(TemplateView):
    """«Цены товаров»: типы расчётных цен и наценки на товар."""

    template_name = 'product_pricing/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # order_by явно: Meta.ordering к запросам с агрегацией Django не применяет.
        types = (ProductPriceType.objects.annotate(prices_count=Count('prices'))
                 .order_by(*ProductPriceType._meta.ordering))
        rules = (ProductPriceRule.objects.select_related('price_type')
                 .prefetch_related('categories', 'brands', 'products')
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
                self.after_delete()
            except ProtectedError:
                messages.error(request, self.protected_message)
            return HttpResponseClientRefresh()
        return super().post(request, *args, **kwargs)

    def after_delete(self):
        pass


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


class _RuleFormMixin:
    """Модалка наценки: своя разметка и пересчёт сразу после сохранения —
    чтобы результат был виден на «Товарах», а не «после следующего пересчёта»."""

    model = ProductPriceRule
    form_class = ProductPriceRuleForm
    template_name = 'product_pricing/partials/rule_form.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        dispatch_after_commit(update_product_prices_task)
        return response

    def after_delete(self):
        dispatch_after_commit(update_product_prices_task)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pk = self.object.pk if getattr(self, 'object', None) else ''
        context['preview_url'] = f"{reverse('product-price-rule-preview')}?pk={pk}" if pk else \
            reverse('product-price-rule-preview')
        return context


class ProductPriceRuleCreate(_RuleFormMixin, _ModalFormMixin, CreateView):
    extra_context = {'title': 'Новая наценка'}
    success_message = 'Наценка добавлена, цены пересчитываются'

    def get_initial(self):
        """?product=<pk> — «Наценка на этот товар» с карточки товара: товар уже
        выбран, а приоритет выше общих наценок (по умолчанию у них 100), иначе
        такая наценка почти всегда проигрывала бы им."""
        initial = super().get_initial()
        first_type = ProductPriceType.objects.first()
        if first_type:
            initial['price_type'] = first_type.pk
        product_pk = self.request.GET.get('product')
        if product_pk and product_pk.isdigit():
            initial['products'] = [product_pk]
            initial['priority'] = PRODUCT_RULE_PRIORITY
        return initial


class ProductPriceRuleUpdate(_RuleFormMixin, _ModalDeleteMixin, _ModalFormMixin, UpdateView):
    extra_context = {'title': 'Наценка', 'can_delete': True,
                     'delete_confirm': 'Удалить наценку? Её цены исчезнут после пересчёта.'}
    success_message = 'Наценка сохранена, цены пересчитываются'
    delete_message = 'Наценка удалена'


class ProductPriceRulePreview(View):
    """Предпросмотр наценки по текущему состоянию формы — ещё до сохранения.

    Форма может быть недозаполнена или с ошибками: берём то, что уже
    разобралось (form.instance собирается из валидных полей даже у
    невалидной формы), и показываем, что получилось бы.
    """

    def post(self, request, *args, **kwargs):
        instance = None
        if request.GET.get('pk'):
            instance = ProductPriceRule.objects.filter(pk=request.GET['pk']).first()
        form = ProductPriceRuleForm(request.POST, instance=instance)
        form.is_valid()
        rule = form.instance
        context = {'rule': rule, 'errors': form.errors}
        if rule.price_type_id:
            cleaned = getattr(form, 'cleaned_data', {})
            categories = list(cleaned.get('categories') or [])
            brands = list(cleaned.get('brands') or [])
            products = list(cleaned.get('products') or [])
            context['preview'] = preview_rule(rule, categories=categories,
                                              brand_ids=[brand.pk for brand in brands],
                                              product_ids=[product.pk for product in products])
            context['scope_label'] = rule.scope_label(categories=categories, brands=brands, products=products)
        return render(request, 'product_pricing/partials/rule_preview.html', context)
