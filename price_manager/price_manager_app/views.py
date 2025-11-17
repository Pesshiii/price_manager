from django.contrib import messages
from django.db.models import Q
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView
from django_tables2.views import SingleTableMixin, SingleTableView

from price_manager_app.forms import PriceManagerForm
from price_manager_app.models import PriceManager
from price_manager_app.services import get_price_query
from price_manager_app.tables import PriceManagerListTable
from supplier_manager.models import Discount, SupplierProduct, SP_PRICES
from supplier_manager.tables import SupplierProductPriceManagerTable


class PriceManagerList(SingleTableView):
    model = PriceManager
    table_class = PriceManagerListTable
    template_name = 'price_manager/list.html'


class PriceManagerCreate(SingleTableMixin, CreateView):
    model = PriceManager
    form_class = PriceManagerForm
    table_class = SupplierProductPriceManagerTable
    success_url = '/price-manager/'
    template_name = 'price_manager/create.html'

    def get_table_data(self):
        products = SupplierProduct.objects.all()
        if not hasattr(self, 'cleaned_data'):
            return products
        cleaned_data = self.cleaned_data
        products = products.filter(supplier=cleaned_data['supplier'])
        if cleaned_data['has_rrp'] is not None:
            if cleaned_data['has_rrp']:
                products = products.filter(rrp__gt=0)
            else:
                products = products.filter(rrp=0)
        if cleaned_data['discounts']:
            products = products.filter(discounts__in=cleaned_data['discounts'])
        if cleaned_data['source'] in SP_PRICES:
            products = products.filter(
                get_price_query(cleaned_data['price_from'], cleaned_data['price_to'], cleaned_data['source'])
            )
        else:
            products = products.filter(
                get_price_query(
                    cleaned_data['price_from'],
                    cleaned_data['price_to'],
                    f"main_product__{cleaned_data['source']}",
                )
            )
        return products

    def get_form(self):
        form = super().get_form(self.form_class)
        discounts = Discount.objects.filter(supplier=form['supplier'].value())
        choices = [(None, 'Все группы скидок')]
        choices.extend([(disc.id, disc.name) for disc in discounts])
        form.fields['discounts'].choices = choices
        return form

    def form_valid(self, form):
        if not form.is_valid():
            return self.form_invalid(form)
        cleaned_data = form.cleaned_data
        self.cleaned_data = cleaned_data
        if cleaned_data['dest'] == cleaned_data['source']:
            messages.error(self.request, 'Поле не может считатсься от себя же')
            return self.form_invalid(form)
        price_from = cleaned_data['price_from']
        price_to = cleaned_data['price_to']
        if price_from and price_to and price_from >= price_to:
            messages.error(self.request, 'Неверная ценовая зона: "От" больше или равен "До"')
            return self.form_invalid(form)
        if price_to and price_to == 0:
            messages.error(self.request, 'Неверная ценовая зона: "До" равен 0')
            return self.form_invalid(form)
        query = Q()
        if price_from and price_to:
            if price_from == 0:
                query |= Q(price_from__isnull=True)
            else:
                query |= Q(price_from__gte=price_from) & Q(price_from__lte=price_to)
            query |= Q(price_to__gte=price_from) & Q(price_to__lte=price_to)
            query |= Q(price_to__isnull=True) & Q(price_from__lte=price_to)
        elif price_to:
            query |= Q(price_from__lte=price_to)
            query |= Q(price_from__isnull=True)
        elif price_from:
            query |= Q(price_to__gte=price_from)
            query |= Q(price_to__isnull=True)
        conf_price_manager = PriceManager.objects.filter(query)
        if cleaned_data['discounts']:
            conf_price_manager = conf_price_manager.filter(
                Q(discounts__in=cleaned_data['discounts']) | Q(discounts__isnull=True)
            )
        if cleaned_data['has_rrp'] is None:
            conf_price_manager = conf_price_manager.filter(
                Q(has_rrp__isnull=True) | Q(has_rrp=True) | Q(has_rrp=False)
            )
        elif cleaned_data['has_rrp']:
            conf_price_manager = conf_price_manager.filter(Q(has_rrp=True) | Q(has_rrp__isnull=True))
        else:
            conf_price_manager = conf_price_manager.filter(Q(has_rrp=False) | Q(has_rrp__isnull=True))
        conf_price_manager = conf_price_manager.filter(dest=cleaned_data['dest'])
        conf_price_manager = conf_price_manager.filter(supplier=cleaned_data['supplier'])
        if conf_price_manager.exists():
            messages.error(self.request, f"Пересечение с другой наценкой: {conf_price_manager.first().name}")
            return self.form_invalid(form)
        if self.request.POST.get('btn') != 'save':
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, 'Наценка успешно добавлена')
        return super().form_invalid(form)


class PriceManagerUpdate(SingleTableMixin, UpdateView):
    model = PriceManager
    form_class = PriceManagerForm
    table_class = SupplierProductPriceManagerTable
    success_url = '/price-manager/'
    template_name = 'price_manager/create.html'
    pk_url_kwarg = 'id'

    def get_table_data(self):
        products = SupplierProduct.objects.all()
        if not hasattr(self, 'cleaned_data'):
            return products
        cleaned_data = self.cleaned_data
        products = products.filter(supplier=cleaned_data['supplier'])
        if cleaned_data['has_rrp'] is not None:
            if cleaned_data['has_rrp']:
                products = products.filter(rrp__gt=0)
            else:
                products = products.filter(rrp=0)
        if cleaned_data['discounts']:
            products = products.filter(discounts__in=cleaned_data['discounts'])
        if cleaned_data['source'] in SP_PRICES:
            products = products.filter(
                get_price_query(cleaned_data['price_from'], cleaned_data['price_to'], cleaned_data['source'])
            )
        else:
            products = products.filter(
                get_price_query(
                    cleaned_data['price_from'],
                    cleaned_data['price_to'],
                    f"main_product__{cleaned_data['source']}",
                )
            )
        return products

    def get_form(self):
        form = super().get_form(self.form_class)
        discounts = Discount.objects.filter(supplier=form['supplier'].value())
        choices = [(None, 'Все группы скидок')]
        choices.extend([(disc.id, disc.name) for disc in discounts])
        form.fields['discounts'].choices = choices
        return form

    def form_valid(self, form):
        if not form.is_valid():
            return self.form_invalid(form)
        self.cleaned_data = form.cleaned_data
        if self.request.POST.get('btn') != 'save':
            return self.form_invalid(form)
        form.save()
        messages.success(self.request, 'Наценка успешно обновлена')
        return super().form_invalid(form)


class PriceManagerDetail(DetailView):
    model = PriceManager
    template_name = 'price_manager/detail.html'
    pk_url_kwarg = 'id'
    context_object_name = 'price_manager'


class PriceManagerDelete(DeleteView):
    model = PriceManager
    template_name = 'price_manager/confirm_delete.html'
    pk_url_kwarg = 'id'
    success_url = '/price-manager/'
