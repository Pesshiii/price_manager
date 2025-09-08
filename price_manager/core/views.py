# Импорты из django
from django.shortcuts import (render,
                              redirect,
                              get_object_or_404,
                              HttpResponse,
                              )
from django.http import HttpResponseRedirect, HttpResponse
from django.template.loader import render_to_string
from django.contrib import messages
from django.views.generic import (View,
                                  ListView,
                                  DetailView,
                                  CreateView,
                                  UpdateView,
                                  DeleteView,
                                  FormView,
                                  TemplateView)
from django.views.decorators.http import require_POST
from django.urls import reverse
from django_tables2 import SingleTableView, RequestConfig, SingleTableMixin
from django_filters.views import FilterView
from decimal import Decimal, InvalidOperation

# Импорты моделей, функций, форм, таблиц
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from .forms import *
from .tables import *
from .filters import *

# Импорты сторонних библиотек
import pandas as pd
import json
import math

def to_dec(v):
    """Безопасно преобразует значение к Decimal(0) при None/''/ошибках."""
    try:
        if v is None or v == '':
            return Decimal(0)
        # str(...) чтобы избежать артефактов float
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)

@require_POST
def toggle_basket(request, pk):
    basket = request.session.setdefault('basket', [])
    pk = int(pk)

    if pk in basket:
        basket.remove(pk)
    else:
        basket.append(pk)

    request.session.modified = True

    # return only the fresh button
    html = render_to_string(
        'main/product/actions.html',
        {
            'record': get_object_or_404(MainProduct, pk=pk),
            'basket': basket,
        },
        request=request
    )
    return HttpResponse(html)


class MainPage(SingleTableMixin, FilterView):
    model = MainProduct
    filterset_class = MainProductFilter
    table_class = MainProductListTable
    template_name = 'main/main.html'

    def get_table(self, **kwargs):
        return super().get_table(**kwargs, request=self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


# Обработка поставщика

class SupplierList(SingleTableView):
    '''Список поставщиков на <<supplier/>>'''
    model = Supplier
    table_class = SupplierListTable
    template_name = 'supplier/list.html'


class SupplierSettingList(SingleTableView):
    '''Список Настроек на транице <<supplier/<int:id>/settings/>>'''
    model = Setting
    table_class = SettingListTable
    template_name = 'supplier/settings.html'

    def get_table_data(self):
        return Setting.objects.filter(supplier_id=self.kwargs['id'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['supplier_id'] = self.kwargs['id']
        context['supplier'] = Supplier.objects.get(id=context['supplier_id'])
        return context


class SupplierDetail(SingleTableView):
    '''
  Таблица отображения товаров на странице поставщиков
  <<supplier/<int:id>/>>
  '''

    model = SupplierProduct
    table_class = SupplierProductListTable
    template_name = 'supplier/detail.html'

    def get_queryset(self):
        queryset = super().get_queryset().search_fields(self.request.GET).filter(
            supplier_id=self.kwargs['id'])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['supplier_id'] = self.kwargs['id']
        context['supplier'] = Supplier.objects.get(id=context['supplier_id'])
        context['filter_form'] = SupplierFilterForm(self.request.GET or None)
        return context


class SupplierCreate(CreateView):
    '''Таблица создания Поставщиков <<supplier/create/>>'''
    model = Supplier
    fields = '__all__'
    success_url = '/supplier'
    template_name = 'supplier/create.html'


class SupplierDelete(DeleteView):
    model = Supplier
    success_url = '/supplier/'
    pk_url_kwarg = 'id'
    template_name = 'supplier/confirm_delete.html'


class SupplierUpdate(UpdateView):
    '''Таблица  обновления Поставщиков <<supplier/update/>>'''
    model = Supplier
    fields = '__all__'
    success_url = '/supplier'
    template_name = 'supplier/update.html'
    pk_url_kwarg = 'id'


# Обработка настройки

class SettingCreate(CreateView):
    '''Создание настроек <<supplier/<int:id>/setting/create/<int:f_id>/>>'''
    model = Setting
    form_class = SettingForm
    template_name = 'supplier/setting/create.html'

    def get_form(self, **kwargs):
        form = super().get_form(**kwargs)
        # Сетап листов и датафрейма
        self.file_model = FileModel.objects.get(id=self.kwargs['f_id'])
        excel_file = pd.ExcelFile(self.file_model.file)
        choices = [(name, name) for name in excel_file.sheet_names]
        # Установка начальных значений
        form.fields['sheet_name'].choices = choices
        form.fields['supplier'].initial = Supplier.objects.get(id=self.kwargs['id'])
        try:
            sheet_name = form.data['sheet_name']
        except:
            sheet_name = choices[0][0]
        self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')

        # Закрыть файл
        self.file_model.file.close()

        # Подготовка табличек для замены значений(с вводом для филлера пустых полей)
        initial = extract_initial_from_post(self.request.POST, 'widget_form', {'key': ''}, len(self.df.columns))
        self.ins_initial = extract_initial_from_post(self.request.POST, 'initial_form', {'initial': ''}, len(LINKS) - 1)
        self.dict_formset = {}
        self.initial_formset = InitialsFormSet(initial=self.ins_initial, prefix='initial_form')
        InDictFormSet = forms.formset_factory(DictForm, extra=0)
        for key in LINKS.keys():
            if key == '': continue
            dict_initial = extract_initial_from_post(self.request.POST, f'dict_{key}_form',
                                                     {'key': '', 'value': '', 'enable': True})
            if dict_initial == []:
                dict_initial = [{'key': '', 'value': None}]
            self.dict_formset[key] = InDictFormSet(initial=dict_initial, prefix=f'dict_{key}_form')

        self.mapping = {initial[i]['key']: self.df.columns[i]
                        for i in range(len(self.df.columns))
                        if not initial[i]['key'] == ''}

        for key, value in LINKS.items():
            if key == '': continue
            initial_value = self.ins_initial[list(LINKS.keys()).index(key) - 1]['initial']
            if not key in self.mapping and not initial_value == '':
                buf = 0
                while f"{value}{' копия' * buf}" in self.df.columns: buf += 1
                self.df[f"{value}{' копия' * buf}"] = initial_value
                self.mapping[key] = f"{value}{' копия' * buf}"
                initial.append({'key': key})

        #  подготовка шторок на столбцы
        LinkFactory = forms.formset_factory(
            form=LinksForm,
            extra=len(self.df.columns))
        self.link_factory = LinkFactory(initial=initial, prefix='widget_form')

        return form

    def form_valid(self, form):
        unique = []
        for i in range(len(self.df.columns)):
            if f'form-{i}-key' in self.link_factory.data:
                buff = self.link_factory.data[f'form-{i}-key']
                if buff in unique and buff:
                    form.add_error(None, 'Не уникальные поля')
                    return self.form_invalid(form)
                unique.append(buff)
        if 'article' not in self.mapping:
            form.add_error(None, 'Не выбрано поле Артикул')
            return self.form_invalid(form)
        if 'name' not in self.mapping:
            form.add_error(None, 'Не выбрано поле Наименование')
            return self.form_invalid(form)
        # Очистка данных
        if 'priced_only' in form.data and form.data['priced_only']:
            failed_prices = []
            for price in PRICE_FIELDS:
                if not price in self.mapping:
                    failed_prices.append(price)
                    continue
                self.df = self.df[self.df[self.mapping[price]].notnull()]
            if len(failed_prices) == len(PRICE_FIELDS):
                form.add_error(None, 'Не выбрано поле цены')
                return self.form_invalid(form)
        self.df = self.df[self.df[self.mapping['article']].notnull()]
        self.df = self.df[self.df[self.mapping['name']].notnull()]

        # Логика замены значений
        for key in LINKS.keys():
            if key == '' or not key in self.mapping:
                continue
            value = self.mapping[key]

            # Изначальные значения
            indx = list(LINKS.keys()).index(key) - 1
            if not self.ins_initial[indx]['initial'] == '':
                try:
                    self.df.fillna({value: self.ins_initial[indx]['initial']}, inplace=True)
                except BaseException as ex:
                    form.add_error(None, f'Что-то не так с начальными данными: {ex}')

            # Заменки
            action = self.request.POST.get(f'{key}_action')
            dict_initial = extract_initial_from_post(self.request.POST, f'dict_{key}_form',
                                                     {'key': '', 'value': '', 'enable': True})
            if action == 'add':
                ExtraFormSet = forms.formset_factory(DictForm, extra=1, can_delete=True)
                self.dict_formset[key] = ExtraFormSet(initial=dict_initial, prefix=f'dict_{key}_form')
            try:
                col_dict = {item['key']: item['value'] for item in dict_initial if item['enable']}
                dtype = self.df[value].dtype
                self.df[value] = self.df[value].astype(str)
                self.df[value] = self.df[value].replace(col_dict, regex=True)
                self.df[value] = self.df[value].astype(dtype)
            except BaseException as ex:
                form.add_error(None, f'Что-то не так с заменами: {ex}')
        if not self.request.POST.get('submit-btn') == 'save':
            return super().form_invalid(form)
        setting = form.save()
        self.success_url = reverse('setting-upload', kwargs={'id': setting.id, 'f_id': self.file_model.id})
        for key, value in self.mapping.items():
            initial = self.ins_initial[list(LINKS.keys()).index(key) - 1]['initial']
            link = Link.objects.create(
                setting=setting,
                initial=initial,
                key=key,
                value=value
            )
            dict_formset = DictFormSet(self.request.POST, prefix=f'dict_{key}_form')
            if dict_formset.is_valid():
                for i, cleaned in enumerate(dict_formset.cleaned_data):
                    if not cleaned or not cleaned.get('enable'):
                        continue
                    Dict.objects.create(
                        link=link,
                        key=cleaned.get('key', ''),
                        value=cleaned.get('value', '')
                    )
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['link_factory'] = self.link_factory
        context['LINKS'] = LINKS
        # Таблички замен и формы для них
        context['dict_forms'] = self.dict_formset.items()
        context['initial_formset'] = self.initial_formset
        context['initial_forms'] = {
            list(LINKS.keys())[i]: self.initial_formset[i - 1] for i in range(1, len(LINKS))
        }
        tables = {key: DictFormTable(value.forms) for key, value in self.dict_formset.items()}
        context['tables'] = tables
        widgets = [self.link_factory.forms[i]
                   for i in range(len(self.df.columns))]
        context['table'] = get_link_create_table()(df=self.df, widgets=widgets, data=self.df.to_dict('records'))
        RequestConfig(self.request).configure(context['table'])
        return context


class SettingUpdate(UpdateView):
    '''Обновление настройки <</setting/<int:id>/update/<int:f_id>/>>'''
    model = Setting
    form_class = SettingForm
    template_name = 'supplier/setting/create.html'
    pk_url_kwarg = 'id'

    def get_form(self, **kwargs):
        form = super().get_form(**kwargs)
        # Сетап листов и датафрейма
        self.file_model = FileModel.objects.get(id=self.kwargs['f_id'])
        excel_file = pd.ExcelFile(self.file_model.file)
        choices = [(name, name) for name in excel_file.sheet_names]
        # Установка начальных значений
        form.fields['sheet_name'].choices = choices
        try:
            sheet_name = form.data['sheet_name']
        except:
            sheet_name = choices[0][0]
        self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')

        # Закрыть файл
        self.file_model.file.close()

        # Подготовка табличек для замены значений(с вводом для филлера пустых полей)
        initial = extract_initial_from_post(self.request.POST, 'widget_form', {'key': ''}, len(self.df.columns))
        if not False in [item['key'] == '' for item in initial]:
            links = Link.objects.filter(setting__id=self.kwargs.get('id', None)).values_list('key', 'value')
            for i in range(len(self.df.columns)):
                for link in links:
                    if self.df.columns[i] == link[1]:
                        initial[i]['key'] = link[0]
        self.ins_initial = extract_initial_from_post(self.request.POST, 'initial_form', {'initial': ''}, len(LINKS) - 1)
        if not False in [item['initial'] == '' for item in self.ins_initial]:
            links = Link.objects.filter(setting__id=self.kwargs.get('id', None)).values_list('key', 'initial')
            for i in range(1, len(LINKS)):
                for link in links:
                    if list(LINKS.keys())[i] == link[0]:
                        if link[1]:
                            self.ins_initial[i - 1]['initial'] = link[1]
        self.dict_formset = {}
        self.initial_formset = InitialsFormSet(initial=self.ins_initial, prefix='initial_form')
        InDictFormSet = forms.formset_factory(DictForm, extra=0)
        for key in LINKS.keys():
            if key == '': continue
            link = Link.objects.filter(setting__id=self.kwargs.get('id', None), key=key).first()
            dict_initial = extract_initial_from_post(self.request.POST, f'dict_{key}_form',
                                                     {'key': '', 'value': '', 'enable': True})
            if dict_initial == []:
                dicts = Dict.objects.filter(link=link).values_list('key', 'value')
                dict_initial = [{'key': item[0], 'value': item[1]} for item in dicts]
            elif dict_initial == []:
                dict_initial = [{'key': '', 'value': ''}]
            self.dict_formset[key] = InDictFormSet(initial=dict_initial, prefix=f'dict_{key}_form')

        self.mapping = {initial[i]['key']: self.df.columns[i]
                        for i in range(len(self.df.columns))
                        if not initial[i]['key'] == ''}

        for key, value in LINKS.items():
            if key == '': continue
            initial_value = self.ins_initial[list(LINKS.keys()).index(key) - 1]['initial']
            if not key in self.mapping and not initial_value == '':
                buf = 0
                while f"{value}{' копия' * buf}" in self.df.columns: buf += 1
                self.df[f"{value}{' копия' * buf}"] = initial_value
                self.mapping[key] = f"{value}{' копия' * buf}"
                initial.append({'key': key})

        #  подготовка шторок на столбцы
        LinkFactory = forms.formset_factory(
            form=LinksForm,
            extra=len(self.df.columns))
        self.link_factory = LinkFactory(initial=initial, prefix='widget_form')

        return form

    def form_valid(self, form):
        unique = []
        for i in range(len(self.df.columns)):
            if f'form-{i}-key' in self.link_factory.data:
                buff = self.link_factory.data[f'form-{i}-key']
                if buff in unique and buff:
                    form.add_error(None, 'Не уникальные поля')
                    return self.form_invalid(form)
                unique.append(buff)
        if 'article' not in self.mapping:
            form.add_error(None, 'Не выбрано поле Артикул')
            return self.form_invalid(form)
        if 'name' not in self.mapping:
            form.add_error(None, 'Не выбрано поле Наименование')
            return self.form_invalid(form)
        # Очистка данных
        if 'priced_only' in form.data and form.data['priced_only']:
            failed_prices = []
            for price in PRICE_FIELDS:
                if not price in self.mapping:
                    failed_prices.append(price)
                    continue
                self.df = self.df[self.df[self.mapping[price]].notnull()]
            if len(failed_prices) == len(PRICE_FIELDS):
                form.add_error(None, 'Не выбрано поле цены')
                return self.form_invalid(form)
        self.df = self.df[self.df[self.mapping['article']].notnull()]
        self.df = self.df[self.df[self.mapping['name']].notnull()]

        # Логика замены значений
        for key in LINKS.keys():
            if key == '' or not key in self.mapping:
                continue
            value = self.mapping[key]

            # Изначальные значения
            indx = list(LINKS.keys()).index(key) - 1
            if not self.ins_initial[indx]['initial'] == '':
                try:
                    self.df.fillna({value: self.ins_initial[indx]['initial']}, inplace=True)
                except BaseException as ex:
                    form.add_error(None, f'Что-то не так с начальными данными: {ex}')

            # Заменки
            action = self.request.POST.get(f'{key}_action')
            dict_initial = extract_initial_from_post(self.request.POST, f'dict_{key}_form',
                                                     {'key': '', 'value': '', 'enable': True})
            if action == 'add':
                ExtraFormSet = forms.formset_factory(DictForm, extra=1, can_delete=True)
                self.dict_formset[key] = ExtraFormSet(initial=dict_initial, prefix=f'dict_{key}_form')
            try:
                col_dict = {item['key']: item['value'] for item in dict_initial if item['enable']}
                dtype = self.df[value].dtype
                self.df[value] = self.df[value].astype(str)
                self.df[value] = self.df[value].replace(col_dict, regex=True)
                self.df[value] = self.df[value].astype(dtype)
            except BaseException as ex:
                form.add_error(None, f'Что-то не так с заменами: {ex}')
        if not self.request.POST.get('submit-btn') == 'save':
            return super().form_invalid(form)
        setting = form.save()
        self.success_url = reverse('setting-upload', kwargs={'id': setting.id, 'f_id': self.file_model.id})
        Link.objects.filter(setting=setting).delete()
        for key, value in self.mapping.items():
            initial = self.ins_initial[list(LINKS.keys()).index(key) - 1]['initial']
            link = Link.objects.create(
                setting=setting,
                initial=initial,
                key=key,
                value=value
            )
            dict_formset = DictFormSet(self.request.POST, prefix=f'dict_{key}_form')
            if dict_formset.is_valid():
                for i, cleaned in enumerate(dict_formset.cleaned_data):
                    if not cleaned or not cleaned.get('enable'):
                        continue
                    Dict.objects.create(
                        link=link,
                        key=cleaned.get('key', ''),
                        value=cleaned.get('value', '')
                    )
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['link_factory'] = self.link_factory
        context['LINKS'] = LINKS
        # Таблички замен и формы для них
        context['dict_forms'] = self.dict_formset.items()
        context['initial_formset'] = self.initial_formset
        context['initial_forms'] = {
            list(LINKS.keys())[i]: self.initial_formset[i - 1] for i in range(1, len(LINKS))
        }
        tables = {key: DictFormTable(value.forms) for key, value in self.dict_formset.items()}
        context['tables'] = tables
        widgets = [self.link_factory.forms[i]
                   for i in range(len(self.df.columns))]
        context['table'] = get_link_create_table()(df=self.df, widgets=widgets, data=self.df.to_dict('records'))
        RequestConfig(self.request).configure(context['table'])
        return context


class SettingDelete(DeleteView):
    model = Setting
    template_name = 'supplier/setting/confirm_delete.html'
    pk_url_kwarg = 'id'

    def get_success_url(self):
        return f'''/supplier/{self.get_object().supplier.pk}/settings'''


class SettingDetail(SingleTableView):
    '''Отображает настройку поставщика <<setting/<int:id>/>>'''
    model = Link
    table_class = LinkListTable
    template_name = 'supplier/setting/detail.html'

    def get_table_data(self):
        return Link.objects.filter(setting_id=self.kwargs['id'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['setting_id'] = self.kwargs['id']
        context['setting'] = Setting.objects.get(id=context['setting_id'])
        return context


class SettingUpload(View):
    def get(self, request, *args, **kwargs):
        return SettingDisplay.as_view()(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return upload_supplier_products(request, *args, **kwargs)


class SettingDisplay(DetailView):
    '''Проверка данных перед загрузкой <<setting/<int:id>/upload/<int:f_id>/>>'''
    model = Setting
    template_name = 'supplier/setting/upload.html'
    pk_url_kwarg = 'id'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        setting = self.get_object()
        context['setting'] = setting
        context['supplier'] = setting.supplier
        file_model = FileModel.objects.get(id=self.kwargs['f_id'])
        try:
            excel_file = pd.ExcelFile(file_model.file)
            mapping = {get_field_details(SupplierProduct)[link.key]['verbose_name']: link.value for link in
                       Link.objects.filter(setting=setting)}
            links = {link.key: link.value for link in Link.objects.all().filter(setting=setting)}
            self.df = excel_file.parse(setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
            file_model.file.close()
            for link in Link.objects.all().filter(setting=setting):
                if link.value not in self.df.columns:
                    self.df[link.value] = link.initial
            self.df = self.df[mapping.values()]
            if setting.priced_only:
                for price in PRICE_FIELDS:
                    if not price in mapping:
                        continue
                    self.df = self.df[self.df[mapping[price]].notnull()]
            self.df = self.df[self.df[links['article']].notnull()]
            self.df = self.df[self.df[links['name']].notnull()]
            # Применение заменок
            for link in Link.objects.filter(setting_id=setting.id):
                col_dict = {entry.key: entry.value for entry in Dict.objects.filter(link=link)}
                try:
                    self.df[link.value] = self.df[link.value].fillna(link.initial)
                except BaseException as ex:
                    messages.error(None, f'Что-то не так с начальными данными: {ex}')
                try:
                    dtype = self.df[link.value].dtype
                    self.df[link.value] = self.df[link.value].astype(str)
                    self.df[link.value] = self.df[link.value].replace(col_dict, regex=True)
                    self.df[link.value] = self.df[link.value].astype(dtype)
                except BaseException as ex:
                    messages.error(None, f'Что-то не так с заменами: {ex}')
            table = get_upload_list_table()(mapping=mapping, data=self.df.to_dict('records'))
            RequestConfig(self.request, paginate=True).configure(table)
            context['table'] = table
        except BaseException as ex:
            messages.error(self.request, ex)
            file_model.file.delete()
            file_model.delete()
        return context

    def render_to_response(self, context, **response_kwargs):
        try:
            if self.df.empty:
                return redirect('supplier')
        except:
            return redirect('supplier')
        if not 'table' in context:
            return redirect('supplier')
        return super().render_to_response(context, **response_kwargs)


# Обработка файлов

class FileUpload(CreateView):
    '''
  Загрузка файла <<upload/<str:name>/<int:id>/>>
  name - url name to link after
  '''
    model = FileForm
    form_class = FileForm
    template_name = 'upload/upload.html'

    def form_valid(self, form):
        f_id = form.save().id
        id = self.kwargs.get('id', 0)
        if not id == 0:
            self.success_url = reverse(self.kwargs['name'],
                                       kwargs={'id': id, 'f_id': f_id})
        else:
            self.success_url = reverse(self.kwargs['name'],
                                       kwargs={'f_id': f_id})
        return super().form_valid(form)


# Обработка продуктов

# !!!Временно: добавить класс удаления потом!!!
def delete_supplier_product(request, **kwargs):
    '''
  Подвязка к функции удаления на странице поставщика
  <<supplier-product/<int:id>/delete/>>
  '''
    product = SupplierProduct.objects.get(id=kwargs['id'])
    id = product.supplier.id
    product.delete()
    return redirect('supplier-detail', id=id)


# !!!Временно: не загружать через ссылку!!!

def upload_supplier_products(request, **kwargs):
    from django.utils import timezone
    from django.db import transaction
    from django.shortcuts import redirect, get_object_or_404
    from django.db.models import Sum
    import pandas as pd
    from decimal import Decimal, ROUND_HALF_UP

    def _to_int(v, default=0):
        try:
            x = pd.to_numeric(v, errors='coerce')
            return int(x) if pd.notna(x) else default
        except Exception:
            try:
                return int(Decimal(str(v)))
            except Exception:
                return default

    def _to_float(v, default=0.0):
        try:
            x = pd.to_numeric(v, errors='coerce')
            return float(x) if pd.notna(x) else default
        except Exception:
            try:
                return float(Decimal(str(v)))
            except Exception:
                return default

    def _to_dec(v):
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            try:
                return Decimal(str(_to_float(v, 0.0)))
            except Exception:
                return None

    def _q2(val: Decimal | None) -> Decimal | None:
        if val is None:
            return None
        return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    setting = get_object_or_404(Setting, id=kwargs['id'])
    supplier = setting.supplier
    file_model = get_object_or_404(FileModel, id=kwargs['f_id'])

    # режим сопоставления с MainProduct
    match_mode = (request.GET.get('match') or 'article').strip().lower()
    if match_mode not in ('article', 'article_manufacturer', 'article_name'):
        match_mode = 'article'

    # курс (тенге за единицу валюты)
    try:
        rate = _to_dec(setting.currency.value)
        if rate is None or rate <= 0:
            raise ValueError("Курс валюты должен быть > 0")
    except Exception as ex:
        from django.contrib import messages
        messages.error(request, f"Некорректный курс валюты в настройке: {ex}")
        return redirect('supplier-detail', id=supplier.id)

    # соберём маппинг "ключ_поля модели" -> "имя колонки в файле"
    links = {link.key: link.value for link in Link.objects.filter(setting_id=setting.id)}

    upload_dt = getattr(file_model, 'created_at', None) or timezone.now()
    has_stock = 'stock' in links
    has_price_any = any(k in links for k in ('supplier_price', 'supplier_price_kzt'))  # старые настройки терпим
    to_update_supplier_fields = []
    if has_stock:
        supplier.last_stock_upload_at = upload_dt
        to_update_supplier_fields.append('last_stock_upload_at')
    if has_price_any:
        supplier.last_price_upload_at = upload_dt
        to_update_supplier_fields.append('last_price_upload_at')
    if to_update_supplier_fields:
        try:
            supplier.save(update_fields=to_update_supplier_fields)
        except Exception:
            pass

    # читаем Excel-лист
    try:
        excel_file = pd.ExcelFile(file_model.file)
        df = (excel_file.parse(setting.sheet_name)
              .dropna(axis=0, how='all')
              .dropna(axis=1, how='all'))
    except Exception as ex:
        from django.contrib import messages
        messages.error(request, f"Не удалось прочитать лист '{setting.sheet_name}': {ex}")
        return redirect('supplier-detail', id=supplier.id)
    finally:
        try:
            file_model.file.close()
        except Exception:
            pass

    # обязательные столбцы (из файла)
    from django.contrib import messages
    req_keys = ['article', 'name']
    missing_cols = [links[k] for k in req_keys if k in links and links[k] not in df.columns]
    if missing_cols:
        messages.error(request, f"В файле отсутствуют столбцы: {', '.join(map(str, missing_cols))}")
        return redirect('supplier-detail', id=supplier.id)

    # удалим дубляжи по name+article
    if all(k in links for k in ('name', 'article')):
        df = df.drop_duplicates(subset=[links['name'], links['article']])

    # если отмечено "только строки с ценой" — оставим там, где есть supplier_price > 0
    if setting.priced_only and 'supplier_price' in links and links['supplier_price'] in df.columns:
        sp_col = links['supplier_price']
        mask = pd.to_numeric(df[sp_col], errors='coerce') > 0
        df = df[mask.fillna(False)]

    touched_mp_ids = set()
    created_mp = 0
    created_sp = 0
    updated_sp = 0
    skipped = 0

    def resolve_manufacturer(name: str):
        if not name:
            return None
        name = str(name).strip()
        if not name:
            return None
        obj, _ = Manufacturer.objects.get_or_create(name=name)
        return obj

    def resolve_category(name: str):
        if not name:
            return None
        name = str(name).strip()
        if not name:
            return None
        obj, _ = Category.objects.get_or_create(name=name)
        return obj

    with transaction.atomic():
        for _, row in df.iterrows():
            try:
                art = str(row.get(links.get('article'), '')).strip() if 'article' in links else ''
                nm = str(row.get(links.get('name'), '')).strip() if 'name' in links else ''
                man_name = str(row.get(links.get('manufacturer'), '')).strip() if 'manufacturer' in links else ''
                manufacturer = resolve_manufacturer(man_name) if man_name else None

                if not art:
                    skipped += 1
                    continue

                sp, sp_created = SupplierProduct.objects.get_or_create(
                    supplier=supplier,
                    article=art,
                    defaults={'name': nm}
                )

                # подобрать MainProduct по выбранному режиму
                if match_mode == 'article':
                    mp_qs = MainProduct.objects.filter(supplier=supplier, article=art)
                elif match_mode == 'article_manufacturer':
                    if manufacturer:
                        mp_qs = MainProduct.objects.filter(supplier=supplier, article=art, manufacturer=manufacturer)
                    else:
                        mp_qs = MainProduct.objects.filter(supplier=supplier, article=art, manufacturer__isnull=True)
                else:  # 'article_name'
                    mp_qs = MainProduct.objects.filter(supplier=supplier, article=art, name=nm)

                mp = mp_qs.first()
                if not mp:
                    mp = MainProduct(supplier=supplier, article=art, name=nm or art)
                    if getattr(setting, 'id_as_sku', False):
                        mp.sku = art
                    # остаток
                    if has_stock and links.get('stock') in row:
                        mp.stock = _to_int(row[links['stock']], 0)
                    mp.save()
                    created_mp += 1

                if sp.main_product_id != mp.id:
                    sp.main_product = mp

                # Остаток (если есть колонка)
                if has_stock and links.get('stock') in df.columns:
                    sp.stock = _to_int(row.get(links['stock']), sp.stock or 0)

                # === ЦЕНЫ ===
                # Цена поставщика (в валюте файла)
                supplier_price = None
                if 'supplier_price' in links and links['supplier_price'] in df.columns:
                    supplier_price = _to_dec(row.get(links['supplier_price']))
                sp.supplier_price = float(supplier_price or 0)

                # Цена поставщика в тенге = всегда считаем от supplier_price * rate
                sp.supplier_price_kzt = float(_q2((supplier_price or Decimal('0')) * rate) or 0)

                # === РРЦ ===
                rmp_kzt_val = None
                # 1) если в файле есть и >0 — берём как есть
                if 'rmp_kzt' in links and links['rmp_kzt'] in df.columns:
                    rmp_kzt_val = _to_dec(row.get(links['rmp_kzt']))
                    if rmp_kzt_val is not None and rmp_kzt_val <= 0:
                        rmp_kzt_val = None
                # 2) иначе, если есть rmp_raw — конвертируем
                if rmp_kzt_val is None and 'rmp_raw' in links and links['rmp_raw'] in df.columns:
                    rmp_raw_val = _to_dec(row.get(links['rmp_raw']))
                    sp.rmp_raw = float(_q2(rmp_raw_val) or 0)
                    if rmp_raw_val is not None and rmp_raw_val > 0:
                        rmp_kzt_val = _q2(rmp_raw_val * rate)

                # если в шаге (1) мы уже получили rmp_kzt — сохраняем; если нет и в (2) посчитали — тоже сохранится
                sp.rmp_kzt = float(_q2(rmp_kzt_val) or 0)

                # Прочее
                if nm:
                    sp.name = nm
                if manufacturer:
                    sp.manufacturer = manufacturer
                if 'category' in links and links['category'] in df.columns:
                    cat = resolve_category(row.get(links['category']))
                    if cat:
                        sp.category = cat
                if 'discount' in links and links['discount'] in df.columns:
                    # Если у тебя FK на Discount — подбери по имени
                    disc_name = str(row.get(links['discount']) or '').strip()
                    if disc_name:
                        disc, _ = Discount.objects.get_or_create(name=disc_name)
                        sp.discount = disc

                sp.save()
                if sp_created:
                    created_sp += 1
                else:
                    updated_sp += 1

                # чтобы потом суммарно обновить стоки у MainProduct
                touched_mp_ids.add(mp.id)

            except Exception:
                skipped += 1
                continue

        # агрегированный обновлятор остатков у MainProduct (если был столбец stock)
        if has_stock and touched_mp_ids:
            totals = (SupplierProduct.objects
                      .filter(main_product_id__in=touched_mp_ids)
                      .values('main_product_id')
                      .annotate(total=Sum('stock')))
            totals = {row['main_product_id']: row['total'] for row in totals}
            to_update = list(MainProduct.objects.filter(pk__in=totals.keys()))
            now = timezone.now()
            for p in to_update:
                p.stock = totals.get(p.pk, 0)
                dt = getattr(p.supplier, 'last_stock_upload_at', None) or now
                if hasattr(p, 'updated_at'):
                    p.updated_at = dt
            fields = ['stock']
            if hasattr(MainProduct, '_meta') and any(f.name == 'updated_at' for f in MainProduct._meta.fields):
                fields.append('updated_at')
            MainProduct.objects.bulk_update(to_update, fields=fields)

    from django.contrib import messages
    messages.success(
        request,
        f"Готово. MainProduct: создано {created_mp}. SupplierProduct: создано {created_sp}, обновлено {updated_sp}, пропущено {skipped}."
    )
    return redirect('supplier-detail', id=supplier.id)



# Обработка производителей

class ManufacturerList(SingleTableView):
    '''Отображение производителей <<manufacturer/>>'''
    model = Manufacturer
    table_class = ManufacturerListTable
    template_name = 'manufacturer/list.html'


class ManufacturerDetail(SingleTableView):
    '''Отображение словоря производителя <<manufacturer/<int:id>/>>'''
    model = ManufacturerDict
    table_class = ManufacturerDictListTable
    template_name = 'manufacturer/dict.html'

    def get_table_data(self):
        return ManufacturerDict.objects.filter(manufacturer_id=self.kwargs['id'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['manufacturer_id'] = self.kwargs['id']
        context['manufacturer'] = Manufacturer.objects.get(id=context['manufacturer_id'])
        return context


class ManufacturerCreate(CreateView):
    '''Создание Производителя <<manufacturer/create/>>'''
    model = Manufacturer
    fields = '__all__'
    success_url = '/manufacturer/'
    template_name = 'manufacturer/create.html'


class ManufacturerDictCreate(CreateView):
    '''Обновление словаря Производителя <<manufacturer/<int:id>/add-alt/>>'''
    model = ManufacturerDict
    form_class = ManufacturerDictForm
    template_name = 'manufacturer/create.html'

    def get_form(self):
        form = super().get_form()
        form.fields['manufacturer'].initial = Manufacturer.objects.get(id=self.kwargs['id'])
        return form

    def get_success_url(self):
        return reverse('manufacturer-detail', kwargs={'id': self.kwargs['id']})


# Обработка валюты

class CurrencyList(SingleTableView):
    '''Отображает валюты <</currency/>>'''
    model = Currency
    table_class = CurrencyListTable
    template_name = 'currency/list.html'

    def get_table_data(self):
        return Currency.objects.exclude(name='KZT')


class CurrencyCreate(CreateView):
    model = Currency
    fields = '__all__'
    template_name = 'currency/create.html'

    def get_success_url(self):
        return '/currency/'


class CurrencyUpdate(UpdateView):
    model = Currency
    fields = '__all__'
    template_name = 'currency/update.html'
    pk_url_kwarg = 'id'

    def get_success_url(self):
        return '/currency/'


# Обработка категорий

class CategorySortSupplierProduct(FormView):
    '''Добавление товаров в категорию категорий <<category/>>'''
    model = Category
    template_name = 'category/sort.html'
    success_url = '/category/sort/'
    form_class = CategoryAddForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = SortSupplierProductFilterForm(self.request.GET)
        queryset = SupplierProduct.objects.search_fields(self.request.GET)
        context['table'] = SortSupplierProductTable(queryset)
        RequestConfig(self.request).configure(context['table'])
        return context

    def form_valid(self, form):
        selected_products = self.request.POST.getlist('selected_items')
        category = form.cleaned_data['category']
        queryset = SupplierProduct.objects.search_fields(self.request.GET)
        if selected_products and category:
            queryset.filter(pk__in=selected_products).update(category=category)
        return super().form_valid(form)


class CategoryList(SingleTableView):
    '''Отображение категорий <<category/>>'''
    model = Category
    table_class = CategoryListTable
    template_name = 'category/list.html'


class CategoryCreate(CreateView):
    '''Создание Категории <<category/create/>>'''
    model = Category
    fields = '__all__'
    success_url = '/category/sort/'
    template_name = 'category/create.html'


class CategoryDelete(DeleteView):
    '''Удаление Категории <<category/<<int:id>>delete/>>'''
    model = Category
    pk_url_kwarg = 'id'
    success_url = '/category/'
    template_name = 'category/confirm_delete.html'


# Обработка наценок

class PriceManagerList(SingleTableView):
    '''Отображение наценок <<price_manager/>>'''
    model = PriceManager
    table_class = PriceManagerListTable
    template_name = 'price_manager/list.html'


class PriceManagerCreate(CreateView):
    '''Создание Наценки <<price-manager/create/>>'''
    model = PriceManager
    fields = '__all__'
    success_url = '/price-manager/'
    template_name = 'price_manager/create.html'

    def form_valid(self, form):
        if form.is_valid():
            cleaned_data = form.cleaned_data
            if cleaned_data['dest'] == cleaned_data['source']:
                messages.error(self.request, f'Поле не может считатсься от себя же')
                return self.form_invalid(form)
            price_manager = PriceManager.objects.filter(
                supplier=cleaned_data['supplier'],
                discount=cleaned_data['discount'],
                dest=cleaned_data['dest'],
                price_from__range=(cleaned_data['price_from'], cleaned_data['price_to']),
                price_to__range=(cleaned_data['price_from'], cleaned_data['price_to']),
            ).last()
            if price_manager:
                messages.error(self.request, f'Пересечение с другой наценкой: {price_manager.name}')
                return self.form_invalid(form)
        return super().form_valid(form)


class PriceManagerDetail(DetailView):
    '''Детали Наценки <<price-manager/<int:id>/>>'''
    model = PriceManager
    template_name = 'price_manager/detail.html'
    pk_url_kwarg = 'id'
    context_object_name = 'price_manager'


class PriceManagerDelete(DeleteView):
    model = PriceManager
    template_name = 'price_manager/confirm_delete.html'
    pk_url_kwarg = 'id'
    success_url = '/price-manager/'


def price_manager_apply_all(request, **kwargs):
    from django.db.models import Q, Min
    from django.utils import timezone

    for pm in PriceManager.objects.all():
        cond = (Q(**{f'{pm.source}__gte': pm.price_from}) &
                Q(**{f'{pm.source}__lte': pm.price_to}))

        # Определяем список продуктов, к которым применяем правило
        if pm.source in ['rmp_kzt', 'supplier_price_kzt']:
            sp_qs = SupplierProduct.objects.filter(cond)
            if pm.supplier:
                sp_qs = sp_qs.filter(supplier=pm.supplier)
            mp_ids = sp_qs.values_list('main_product', flat=True)
            products = list(MainProduct.objects.filter(pk__in=mp_ids))
        else:
            products = list(MainProduct.objects.filter(cond))
            if pm.supplier:
                # если в MainProduct есть ссылка на поставщика — фильтруем
                products = [p for p in products if getattr(p, 'supplier_id', None) == pm.supplier_id]

        # Если правило ограничено категорией (discount здесь, судя по коду, — это категория)
        if pm.discount:
            products = [p for p in products if getattr(p, 'category_id', None) == pm.discount_id]

        # Подготавливаем коэффициенты наценки
        markup = to_dec(pm.markup) / Decimal(100)   # 15 -> 0.15
        increase = to_dec(pm.increase)              # фикс. надбавка

        for p in products:
            # Источник цены: минимальная цена среди SupplierProduct либо поле в MainProduct
            if pm.source in ['rmp_kzt', 'supplier_price_kzt']:
                agg_field = pm.source
                sp_min = (SupplierProduct.objects
                          .filter(main_product=p.pk)
                          .aggregate(v=Min(agg_field))['v'])
                price_source = sp_min
            else:
                price_source = getattr(p, pm.source, None)

            price_dec = to_dec(price_source)

            # new = ceil( price * (1 + markup) + increase )
            new_val = (price_dec * (Decimal(1) + markup) + increase).to_integral_value(rounding=ROUND_CEILING)

            # Записываем результат
            setattr(p, pm.dest, int(new_val))
            p.price_manager = pm

            # Обновим updated_at, если поле есть в модели
            if hasattr(p, 'updated_at'):
                price_dt = getattr(getattr(p, 'supplier', None), 'last_price_upload_at', None) or timezone.now()
                p.updated_at = max(getattr(p, 'updated_at', None) or price_dt, price_dt)

        # Готовим список полей для bulk_update
        fields = [pm.dest, 'price_manager']
        if hasattr(MainProduct, '_meta') and any(f.name == 'updated_at' for f in MainProduct._meta.fields):
            fields.append('updated_at')

        MainProduct.objects.bulk_update(products, fields=fields)

    messages.success(request, 'Наценки применены для всех правил.')
    return redirect('main')


def price_manager_apply(request, **kwargs):
    from django.db.models import Q
    id = kwargs.pop('id')
    if not id:
        messages.error(request, 'Нет такой наценки')
        return redirect('price-manager')

    price_manager = PriceManager.objects.get(id=id)

    # Выбираем продукты, на которые действует правило
    if price_manager.source in ['rmp_kzt', 'supplier_price_kzt']:
        supplier_products = SupplierProduct.objects.all()
        if price_manager.price_from:
            supplier_products = supplier_products.filter(
                Q(**{f'{price_manager.source}__gte': price_manager.price_from}))
        if price_manager.price_to:
            supplier_products = supplier_products.filter(
                Q(**{f'{price_manager.source}__lte': price_manager.price_to}))
        products = MainProduct.objects.filter(pk__in=supplier_products.values_list('main_product', flat=True))
    else:
        products = MainProduct.objects.all()
        if price_manager.price_from:
            products = products.filter(Q(**{f'{price_manager.source}__gte': price_manager.price_from}))
        if price_manager.price_to:
            products = products.filter(Q(**{f'{price_manager.source}__lte': price_manager.price_to}))

    if price_manager.supplier:
        # если в MainProduct хранится supplier_id — отфильтруем
        products = products.filter(supplier_id=price_manager.supplier_id)

    if price_manager.discount:
        products = products.filter(discount=price_manager.discount)

    # Коэффициенты наценки
    markup = to_dec(price_manager.markup) / Decimal(100)
    increase = to_dec(price_manager.increase)

    # Обновляем цены
    upd_products = []
    for product in products:
        product.price_manager = price_manager

        if price_manager.source in ['rmp_kzt', 'supplier_price_kzt']:
            sp = SupplierProduct.objects.filter(main_product=product)
            # берём минимальную цену среди связей (чтобы не падать, если first() = None)
            sp_val = sp.order_by(price_manager.source).values_list(price_manager.source, flat=True).first()
            price_source = sp_val
        else:
            price_source = getattr(product, price_manager.source, None)

        price_dec = to_dec(price_source)
        new_val = (price_dec * (Decimal(1) + markup) + increase).to_integral_value(rounding=ROUND_CEILING)
        setattr(product, price_manager.dest, int(new_val))

        # если есть updated_at — обновим
        if hasattr(product, 'updated_at'):
            from django.utils import timezone
            product.updated_at = timezone.now()

        upd_products.append(product)

    MainProduct.objects.bulk_update(upd_products, fields=[price_manager.dest, 'price_manager', 'updated_at'] if hasattr(MainProduct, '_meta') and any(f.name == 'updated_at' for f in MainProduct._meta.fields) else [price_manager.dest, 'price_manager'])
    return redirect('price-manager')



# Обработка продуктов главного прайса

class MainProductUpdate(UpdateView):
    model = MainProduct
    form_class = MainProductForm
    template_name = 'main/product/update.html'
    success_url = '/'
    pk_url_kwarg = 'id'


def sync_main_products(request, **kwargs):
    """Обновляет только остатки (stock) в MainProduct из SupplierProduct"""
    updated = 0
    errors = 0

    supplier_products = SupplierProduct.objects.select_related("main_product").all()

    for sp in supplier_products:
        try:
            if not sp.main_product:
                continue  # пропускаем без связи

            mp = sp.main_product
            mp.stock = sp.stock

        except Exception as ex:
            errors += 1
            messages.error(request, f"Ошибка при обновлении {sp}: {ex}")
    updated = SupplierProduct.objects.bulk_update(supplier_products, ['stock', 'updated_at'])

    messages.success(request, f"Остатки обновлены у {updated} товаров, ошибок: {errors}")
    return price_manager_apply_all(request, **kwargs)

