from decimal import Decimal
import re

import pandas as pd
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q

from .models import (
    SupplierFile,
    Setting,
    Link,
    SupplierProduct,
    Manufacturer,
    Discount,
    Category,
    SP_NUMBERS,
    SP_PRICES,
)
from .forms import DictFormset, LinkFormset, InitialForm, LINKS

CACHE_TTL = 60 * 30


def _sheet_names_cache_key(setting_id: int) -> str:
    return f'supplier-setting:{setting_id}:sheet-names'


def _df_cache_key(setting_id: int, nrows: int | None) -> str:
    suffix = 'all' if nrows is None else nrows
    return f'supplier-setting:{setting_id}:df:{suffix}'


def invalidate_setting_cache(setting_id: int) -> None:
    cache.delete(_sheet_names_cache_key(setting_id))
    cache.delete_many([
        _df_cache_key(setting_id, 100),
        _df_cache_key(setting_id, None),
    ])


def resolve_conflicts(qs):
    def resolve(item):
        cl_name = re.sub(r'\s', ' ', item.name)
        if cl_name == item.name:
            return item
        return SupplierProduct.objects.get_or_create(
            supplier=item.supplier,
            article=item.article,
            name=cl_name,
            defaults={field: getattr(item, field) for field in [*SP_PRICES, 'stock'] if getattr(item, field) is not None},
        )[0]

    return list(map(resolve, qs))


def get_df_sheet_names(pk):
    cached_columns = cache.get(_sheet_names_cache_key(pk))
    if cached_columns is not None:
        return cached_columns
    supplier_file = SupplierFile.objects.filter(setting=pk).first()
    if not supplier_file or not supplier_file.file:
        return None
    columns = pd.ExcelFile(supplier_file.file, engine='calamine').sheet_names
    supplier_file.file.close()
    cache.set(_sheet_names_cache_key(pk), columns, timeout=CACHE_TTL)
    return columns


def get_df(pk, nrows: int | None = 100) -> pd.DataFrame | None:
    cache_key = _df_cache_key(pk, nrows)
    cached_df = cache.get(cache_key)
    if cached_df is not None:
        return cached_df.copy()

    try:
        setting = Setting.objects.get(pk=pk)
    except Setting.DoesNotExist:
        return None

    supplier_file = SupplierFile.objects.filter(setting=pk).first()
    if not supplier_file or not supplier_file.file:
        return None

    df = pd.read_excel(
        supplier_file.file,
        engine='calamine',
        dtype=str,
        sheet_name=setting.sheet_name,
        nrows=nrows,
        index_col=None,
        na_values=[''],
    ).dropna(axis=0, how='all').dropna(axis=1, how='all')
    supplier_file.file.close()
    if df.shape[0] == 0:
        return None
    cache.set(cache_key, df, timeout=CACHE_TTL)
    return df.copy()


def get_dictformset(post, pk, link):
    mlink = Link.objects.get_or_create(setting=pk, key=link)[0]
    return DictFormset(
        post if post else None,
        initial=[{'key': ldict.key, 'value': ldict.value} for ldict in mlink.dicts.all()],
        form_kwargs={'link': link, 'pk': pk},
        prefix=f'{link}-dict',
    )


def get_linkformset(post, pk):
    df = get_df(pk)
    if df is None:
        return None
    setting = Setting.objects.get(pk=pk)
    return LinkFormset(
        post if post else None,
        initial=[
            {'key': Link.objects.filter(setting=setting, value=column).first().key if Link.objects.filter(setting=setting, value=column).exists() else None}
            for column in df.columns
        ],
        prefix='link',
        form_kwargs={'columns': df.columns},
    )


def get_indicts(post, pk):
    indicts = dict()
    for link, name in LINKS.items():
        if link == '':
            continue
        mlink = Link.objects.get_or_create(setting=Setting.objects.get(pk=pk), key=link)[0]
        dict_formset = DictFormset(
            post if post else None,
            initial=[{'key': ldict.key, 'value': ldict.value} for ldict in mlink.dicts.all()],
            form_kwargs={'link': link, 'pk': pk},
            prefix=f'{link}-dict',
        )
        initial = InitialForm(post if post else None, initial={'initial': mlink.initial}, prefix=f'{link}-initial', pk=pk)
        if post and dict_formset.is_valid() and post.get('action'):
            action = post.get('action')
            if 'delete-' + link in action:
                data = []
                for i in range(len(dict_formset.cleaned_data)):
                    if i != int(action.strip(f'delete-{link}-dict-')):
                        data.append(dict_formset.cleaned_data[i])
                dict_formset = DictFormset(initial=data, form_kwargs={'link': link, 'pk': pk}, prefix=f'{link}-dict')
            elif 'add-' + link in action:
                data = dict_formset.cleaned_data
                data.append({})
                dict_formset = DictFormset(initial=data, form_kwargs={'link': link, 'pk': pk}, prefix=f'{link}-dict')
        indicts[link] = {'verbose_name': name, 'initial': initial, 'dict_formset': dict_formset}
    return indicts


def load_setting(pk):
    setting = Setting.objects.get(pk=pk)
    invalidate_setting_cache(pk)
    links = Link.objects.filter(setting=setting)
    df = get_df(pk, nrows=None)
    sps = SupplierProduct.objects.filter(supplier=setting.supplier)
    s_values = map(tuple, sps.values_list('article', 'name'))
    resolve_conflicts(sps)
    if df is None or not links.filter(Q(value__isnull=False) | Q(initial__isnull=False)).exists():
        return None
    for link in links:
        if link.value == '' or link.value is None:
            if link.initial == '' or link.initial is None:
                continue
            df[link.key] = link.initial
        else:
            df = df.rename(columns={link.value: link.key})
            if link.initial not in ('', None):
                df[link.key] = df[link.key].fillna(link.initial)
        df[link.key] = df[link.key].str.replace(r'\s+', ' ', regex=True)
        for dict_item in link.dicts.all():
            df[link.key] = df[link.key].replace(dict_item.key, dict_item.value)
    if 'article' not in df.columns:
        return None
    df = df.loc[:, [link.key for link in links if link.key != '' and link.key in df.columns]]
    df = df.dropna(subset=['article'])
    for link in links:
        if link.key in df.columns and link.key in SP_NUMBERS:
            df[link.key] = pd.to_numeric(df[link.key], errors='coerce')
            df[link.key] = df[link.key].apply(lambda val: val if val >= 0 else None)

    df = df.dropna(subset=[link.key for link in links if link.key not in ('article', 'name') and link.key in df.columns], how='all')

    if 'name' not in df.columns:
        if setting.create_new:
            return None
        _df = df.copy()
        names = _df['article'].apply(lambda article: sps.filter(article=article).values_list('name', flat=True))
        _df['name'] = names
        _df = _df[_df['name'].apply(len) > 0]
        _df = _df.explode('name', ignore_index=True)
        df = _df
    df = df.dropna(subset=['name'])

    df = df.replace({pd.NA: None, float('nan'): None, '': None, 'NaN': None})

    if not setting.create_new:
        mask = df[['article', 'name']].apply(tuple, axis=1).isin(s_values)
        df = df[mask]
    df = df.drop_duplicates(subset=['article', 'name'], keep='first')
    if 'manufacturer' in df.columns:
        df['manufacturer'] = df['manufacturer'].apply(lambda s: Manufacturer.objects.get_or_create(name=s)[0] if s else None)
    if 'discount' in df.columns:
        df['discount'] = df['discount'].apply(lambda s: Discount.objects.get_or_create(supplier=setting.supplier, name=s)[0] if s else None)
    if 'category' in df.columns:
        def _get_category(value):
            if not value:
                return None
            parts = [p.strip() for p in str(value).split('>') if p and str(p).strip()]
            parent = None
            node = None
            if Category.objects.filter(name=parts[-1]).count() == 1:
                return Category.objects.filter(name=parts[-1]).first()
            for name in parts[:10]:
                node, _ = Category.objects.get_or_create(name=name, parent=parent)
                parent = node
            return node

        df['category'] = df['category'].apply(_get_category)

    def get_spmodel(row):
        data = {
            link.key: Decimal(str(getattr(row, link.key))) if link.key in SP_NUMBERS else getattr(row, link.key)
            for link in links
            if link.key not in ('article', 'name') and link.key in df.columns and getattr(row, link.key) is not None
        }
        return SupplierProduct(supplier=setting.supplier, article=row.article, name=row.name, **data)

    sp_model_instances = map(get_spmodel, df.itertuples(index=False))
    sp_update_fields = [link.key for link in links if link.key not in ('article', 'name') and link.key in df.columns]
    sp_update_fields.append('updated_at')
    sps = SupplierProduct.objects.bulk_create(
        sp_model_instances,
        update_conflicts=True,
        update_fields=sp_update_fields,
        unique_fields=['supplier', 'article', 'name'],
    )
    if 'stock' in df.columns:
        setting.supplier.stock_updated_at = timezone.now()
    if set(SP_PRICES).intersection(set(df.columns)):
        setting.supplier.price_updated_at = timezone.now()
    setting.supplier.save()
    return sps
