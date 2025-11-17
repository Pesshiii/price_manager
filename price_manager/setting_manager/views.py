import pandas as pd
import re
from django import forms
from django.contrib import messages
from django.contrib.postgres.search import SearchVector
from django.db.models import Value
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView, View
from django_tables2 import RequestConfig, SingleTableMixin, SingleTableView

from common.utils import extract_initial_from_post
from file_manager.models import FileModel
from main_price.models import Category, MainProduct, Manufacturer
from setting_manager.forms import DictForm, InitialForm, LinkForm, SettingForm
from setting_manager.models import Dict as SettingDict
from setting_manager.models import Link, Setting, LINKS
from setting_manager.tables import (
    DictFormTable,
    LinkListTable,
    SettingListTable,
    get_link_create_table,
    get_upload_list_table,
)
from supplier_manager.models import (
    Discount,
    Supplier,
    SupplierProduct,
    SP_FKS,
    SP_INTEGERS,
    SP_PRICES,
)


class SupplierSettingList(SingleTableView):
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


def clean_headers(df):
    df.columns = [re.sub(r'[\r\n\t]', '', col) for col in df.columns]
    return df


def get_dict_table(request, key, value, link=None):
    dict_initial = extract_initial_from_post(post=request.POST, prefix=f'dict-form-{key}', data={'key': '', 'value': ''})
    extra = int('submit-btn' in request.POST and request.POST['submit-btn'] == key)
    if link:
        dict_initial = [{'key': item.key, 'value': item.value} for item in SettingDict.objects.filter(link=link)]
    if 'delete' in request.POST:
        raw_to_del = request.POST.get('delete')
        idx_del = re.findall(f'{key}-(\\d+)', raw_to_del)
        if idx_del:
            dict_initial.pop(int(idx_del[0]))
    dict_form_set = forms.formset_factory(DictForm, extra=extra)(initial=dict_initial, prefix=f'dict-form-{key}')
    data = [
        {'key': dict_form_set.forms[i]['key'], 'value': dict_form_set.forms[i]['value'], 'btn': f'{key}-{i}'}
        for i in range(len(dict_form_set.forms))
    ]
    if dict_initial or extra == 1:
        table = DictFormTable(data=data)
        RequestConfig(request).configure(table)
        table = table.as_html(request)
    else:
        table = None
    return render_to_string(
        'supplier/setting/dict_table.html',
        context={
            'key': key,
            'value': value,
            'manager': dict_form_set.management_form.as_div(),
            'initial': InitialForm(
                initial={'initial': request.POST.get(f'initial-form-{key}-initial', link.initial if link else '')},
                prefix=f'initial-form-{key}',
            ).as_p(),
            'table': table,
        },
    )


def get_df(df: pd.DataFrame, links, initials, dicts, setting: Setting):
    for column, field in links.items():
        if column not in df.columns:
            df[column] = None
        if field == 'article':
            df = df[df[column].notnull()]
        if field == 'name' and setting.differ_by_name:
            df = df[df[column].notnull()]
        if field in SP_PRICES and setting.priced_only:
            df = df[df[column].notnull()]
        buf: pd.Series = df[column]
        buf = buf.fillna(initials[field])
        buf = buf.astype(str)
        buf = buf.replace(dicts[field], regex=True)
        df[column] = buf
    return df


def get_safe(value, type=None):
    if not type:
        return value
    if value == '':
        return value
    if type == int:
        return int(value)
    if type == float:
        return float(value)
    return value


def convert_sp(value, field):
    if field in SP_PRICES:
        num = float(value) if value else 0
        return 0 if num < 0 else num
    if field in SP_INTEGERS:
        num = int(float(value)) if value else 0
        return 0 if num < 0 else num
    return value


def get_data(df: pd.DataFrame, request, setting: Setting):
    post = request.POST
    links = {
        link['value']: link['key']
        for link in extract_initial_from_post(post, prefix='link-form', data={'key': '', 'value': ''}, length=len(df.columns))
        if link['key'] != ''
    }
    initials = {key: post.get(f'initial-form-{key}-initial', '') for key, value in LINKS.items() if key != ''}
    for key, value in LINKS.items():
        if key == '':
            continue
        buf = value
        if key not in links.values():
            if not initials.get(key):
                continue
            while buf in df.columns:
                buf += ' Копия'
            links[buf] = key
    dicts = {}
    for column_name, field_name in links.items():
        if column_name not in df.columns:
            df[column_name] = None
        initials[field_name] = initials[field_name]
        dicts[field_name] = {}
        for item in extract_initial_from_post(post, prefix=f'dict-form-{field_name}', data={'key': '', 'value': ''}):
            if item['key'] not in dicts[field_name]:
                dicts[field_name][item['key']] = item['value']
    return get_df(df, links, initials, dicts, setting), links, initials, dicts


class SettingCreate(SingleTableMixin, CreateView):
    model = Setting
    form_class = SettingForm
    template_name = 'supplier/setting/create.html'
    prefix = 'setting-form'

    def get_success_url(self):
        return reverse('setting-upload', kwargs={'id': self.setting.pk, 'f_id': self.kwargs.get('f_id')})

    def get_table_class(self):
        return get_link_create_table()

    def get_table(self, **kwargs):
        return super().get_table(**kwargs, columns=list(self.df.columns), links=self.links)

    def get_table_data(self):
        return self.df.to_dict('records')

    def get_form(self):
        form = super().get_form(form_class=self.form_class)
        file_model = FileModel.objects.get(id=self.kwargs['f_id'])
        excel_file = pd.ExcelFile(file_model.file)
        choices = [(name, name) for name in excel_file.sheet_names]
        form.fields['sheet_name'].choices = choices
        form.fields['supplier'].initial = Supplier.objects.get(id=self.kwargs['id'])
        try:
            form.is_valid()
            sheet_name = form.cleaned_data['sheet_name']
        except Exception:
            sheet_name = choices[0][0]
        try:
            self.df = excel_file.parse(sheet_name, nrows=500).dropna(how='all').dropna(axis=1, how='all')
        except Exception:
            self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')
        self.df = clean_headers(self.df)
        file_model.file.close()
        self.df, self.links, self.initials, self.dicts = get_data(self.df, self.request, form.instance)
        return form

    def form_valid(self, form):
        if 'submit-btn' not in self.request.POST or self.request.POST['submit-btn'] != 'save':
            return self.form_invalid(form)
        self.setting = form.instance
        self.setting.save()
        for column_name, field_name in self.links.items():
            link = Link(
                setting=self.setting,
                key=field_name,
                value=column_name,
                initial=str(self.initials[field_name]) if self.initials[field_name] else None,
            )
            link.save()
            for key, value in self.dicts[field_name].items():
                SettingDict(link=link, key=str(key), value=str(value)).save()
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dict_tables = []
        for key, value in LINKS.items():
            if key == '':
                continue
            dict_tables.append(get_dict_table(self.request, key, value))
        context['dict_tables'] = dict_tables
        return context


class SettingUpdate(SingleTableMixin, UpdateView):
    model = Setting
    form_class = SettingForm
    template_name = 'supplier/setting/create.html'
    prefix = 'setting-form'
    pk_url_kwarg = 'id'

    def get_success_url(self):
        return reverse('setting-upload', kwargs={'id': self.setting.pk, 'f_id': self.kwargs.get('f_id')})

    def get_table_class(self):
        return get_link_create_table()

    def get_table(self, **kwargs):
        return super().get_table(**kwargs, columns=list(self.df.columns), links=self.links)

    def get_table_data(self):
        return self.df.to_dict('records')

    def get_form(self):
        form = super().get_form(form_class=self.form_class)
        self.setting = form.instance
        file_model = FileModel.objects.get(id=self.kwargs['f_id'])
        excel_file = pd.ExcelFile(file_model.file)
        choices = [(name, name) for name in excel_file.sheet_names]
        form.fields['sheet_name'].choices = choices
        sheet_name = form.data.get('sheet_name', choices[0][0])
        try:
            self.df = excel_file.parse(sheet_name, nrows=500).dropna(how='all').dropna(axis=1, how='all')
        except Exception:
            self.df = excel_file.parse(sheet_name).dropna(how='all').dropna(axis=1, how='all')
        self.df = clean_headers(self.df)
        file_model.file.close()
        self.df, self.links, self.initials, self.dicts = get_data(self.df, self.request, self.setting)
        if self.links == {}:
            messages.info(self.request, 'Нажмите применить чтобы заработали замены')
            for link in Link.objects.filter(setting__pk=self.setting.pk):
                self.links[link.value] = link.key
                self.initials[link.key] = link.initial
        return form

    def form_valid(self, form):
        if 'submit-btn' not in self.request.POST or self.request.POST['submit-btn'] != 'save':
            return self.form_invalid(form)
        self.setting = form.instance
        Link.objects.filter(setting=self.setting).delete()
        for column_name, field_name in self.links.items():
            link = Link(
                setting=self.setting,
                key=field_name,
                value=column_name,
                initial=str(self.initials[field_name]) if self.initials[field_name] else None,
            )
            link.save()
            for key, value in self.dicts[field_name].items():
                SettingDict(link=link, key=str(key), value=str(value)).save()
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dict_tables = []
        for key, value in LINKS.items():
            if key == '':
                continue
            dict_tables.append(
                get_dict_table(
                    self.request,
                    key,
                    value,
                    Link.objects.filter(setting=self.setting, key=key).first() if self.dicts == {} else None,
                )
            )
        context['dict_tables'] = dict_tables
        return context


class SettingDelete(DeleteView):
    model = Setting
    template_name = 'supplier/setting/confirm_delete.html'
    pk_url_kwarg = 'id'

    def get_success_url(self):
        return f'/supplier/{self.get_object().supplier.pk}/settings'


class SettingDetail(SingleTableView):
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


def get_upload_data(setting: Setting, df: pd.DataFrame):
    links = {link.value: link.key for link in Link.objects.filter(setting=setting)}
    initials = {link.key: link.initial if link.initial else '' for link in Link.objects.filter(setting=setting)}
    dicts = {link.key: {item.key: item.value for item in SettingDict.objects.filter(link=link)} for link in Link.objects.filter(setting=setting)}
    for key, value in LINKS.items():
        if key == '':
            continue
        buf = value
        if key not in links.values():
            if not initials.get(key):
                continue
            while buf in df.columns:
                buf += ' Копия'
            links[buf] = key
    rev_links = {value: key for key, value in links.items()}
    df = get_df(df, links, initials, dicts, setting)
    if setting.differ_by_name:
        df = df.drop_duplicates(subset=[rev_links['name'], rev_links['article']])
    else:
        df = df.drop_duplicates(subset=[rev_links['article']])
    return df, links, initials, dicts


class SettingDisplay(DetailView):
    model = Setting
    template_name = 'supplier/setting/upload.html'
    pk_url_kwarg = 'id'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        setting: Setting = self.get_object()
        context['setting'] = setting
        context['supplier'] = setting.supplier
        file_model = FileModel.objects.get(id=self.kwargs['f_id'])
        try:
            excel_file = pd.ExcelFile(file_model.file)
            try:
                self.df = excel_file.parse(setting.sheet_name, nrows=500).dropna(how='all').dropna(axis=1, how='all')
            except Exception:
                self.df = excel_file.parse(setting.sheet_name).dropna(how='all').dropna(axis=1, how='all')
            self.df = clean_headers(self.df)
            file_model.file.close()
            self.df, self.links, self.initials, self.dicts = get_upload_data(setting, self.df)
            table = get_upload_list_table()(links=self.links, data=self.df.to_dict('records'))
            RequestConfig(self.request, paginate=True).configure(table)
            context['table'] = table
        except Exception as ex:
            messages.error(self.request, ex)
        return context

    def render_to_response(self, context, **response_kwargs):
        if 'table' not in context:
            return redirect('supplier')
        return super().render_to_response(context, **response_kwargs)


def clean_column(column):
    column = column.str.strip()
    column = column.str.replace(r'[^\w\s]', '', regex=True)
    column = column.str.replace(r'\s+', ' ', regex=True)
    return column


def upload_supplier_products(request, **kwargs):
    setting = Setting.objects.get(id=kwargs['id'])
    supplier = setting.supplier
    file_model = FileModel.objects.get(id=kwargs['f_id'])
    excel_file = pd.ExcelFile(file_model.file)
    df = excel_file.parse(setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
    df = clean_headers(df)
    file_model.file.close()
    df, links, initials, dicts = get_upload_data(setting, df)
    rev_links = {value: key for key, value in links.items()}
    discs = {}
    if 'discounts' in rev_links:
        df[rev_links['discounts']] = clean_column(df[rev_links['discounts']])
        discs = {
            disc: Discount.objects.get_or_create(supplier=supplier, name=disc)[0]
            for disc in df[rev_links['discounts']].unique()
        }
    cats = {}
    if 'category' in rev_links:
        cats = {cat: Category.objects.get_or_create(name=cat)[0] for cat in df[rev_links['category']].unique()}
    mans = {}
    if 'manufacturer' in rev_links:
        mans = {man: Manufacturer.objects.get_or_create(name=man)[0] for man in df[rev_links['manufacturer']].unique()}
    sp = []
    mp = []
    new = 0
    overall = 0
    exs = []
    for _, row in df.iterrows():
        if setting.differ_by_name:
            products = list(
                SupplierProduct.objects.filter(
                    supplier=supplier,
                    article=row[rev_links['article']],
                    name=row[rev_links['name']],
                )
            )
        else:
            products = list(
                SupplierProduct.objects.filter(
                    supplier=supplier,
                    article=row[rev_links['article']],
                )
            )
        if not products:
            if setting.differ_by_name and 'name' in rev_links:
                product, created = SupplierProduct.objects.get_or_create(
                    supplier=supplier,
                    article=row[rev_links['article']],
                    name=row[rev_links['name']],
                )
                new += int(created)
                products.append(product)
        for product in products:
            try:
                for column, field in links.items():
                    if field in SP_FKS:
                        if field == 'category':
                            setattr(product, field, cats[row[column]])
                            continue
                        if field == 'discounts':
                            product.discounts.add(discs[row[column]])
                            continue
                        if field == 'manufacturer':
                            setattr(product, field, mans[row[column]])
                            continue
                        continue
                    if field in SP_PRICES:
                        try:
                            setattr(product, field, get_safe(row[column], float))
                        except Exception as ex:
                            messages.error(request, f'Ошибка конвертации цены {row[column]} в поле {field}: {ex}')
                        continue
                    try:
                        setattr(product, field, convert_sp(row[column], field))
                    except Exception as ex:
                        messages.error(request, f'Ошибка конвертации {row[column]} в поле {field}: {ex}')
                if setting.update_main:
                    main_product, main_created = MainProduct.objects.get_or_create(
                        supplier=supplier,
                        article=product.article,
                        name=product.name,
                    )
                    text = main_product._build_search_text()
                    main_product.search_vector = SearchVector(Value(text), config='russian')
                    if main_created and 'category' in rev_links:
                        main_product.category = product.category
                    if main_created and 'manufacturer' in rev_links:
                        main_product.manufacturer = product.manufacturer
                    product.main_product = main_product
                    mp.append(main_product)
                sp.append(product)
                overall += 1
            except Exception as ex:
                exs.append(ex)
    MainProduct.objects.bulk_update(mp, fields=['supplier', 'article', 'name', 'search_vector', 'manufacturer'])
    SupplierProduct.objects.bulk_update(sp, fields=[field for field in links.values() if field != 'discounts'])
    SupplierProduct.objects.bulk_update(sp, fields=['supplier_price', 'rrp', 'main_product'])
    for price in SP_PRICES:
        if price in rev_links:
            supplier.price_updated_at = timezone.now()
    if 'stock' in rev_links:
        supplier.stock_updated_at = timezone.now()
    supplier.save()
    messages.success(request, f'Добавлено товаров: {overall}, Новых: {new}')
    if exs:
        ex_str = '    '.join([f'{ex}' for ex in exs[: min(len(exs), 5)]])
        messages.error(request, f'Ошибок: {len(exs)}.     {ex_str}')
    return redirect('supplier-detail', id=supplier.pk)
