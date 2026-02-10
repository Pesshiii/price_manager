
from django.utils import timezone
from django.db.models import ExpressionWrapper, Q, BooleanField, Value

from .models import (SupplierFile, Setting, Link, 
                     SupplierProduct, Manufacturer, Discount,
                     SP_NUMBERS, SP_PRICES)
from main_product_manager.models import (MainProduct, recalculate_search_vectors)

from .forms import (DictFormset, LinkFormset,
                    InitialForm,
                    LINKS,)
import pandas as pd
import numpy as np
from decimal import Decimal
import re

def resolve_conflicts(qs):
  for item in qs:
    cl_name = re.sub(r'\s', ' ', item.name)
    if not cl_name == item.name:
      sp, created = SupplierProduct.objects.get_or_create(
        supplier = item.supplier, 
        article=item.article, 
        name=cl_name,
        defaults={field:getattr(item, field) for field in [*SP_PRICES, 'stock'] if not getattr(item, field) is None})
      item.delete()
      continue
    elif SupplierProduct.objects.filter(name=cl_name).exclude(pk=item.pk).exists():
      sp, created = SupplierProduct.objects.get_or_create(
        supplier = item.supplier, 
        article=item.article, 
        name=cl_name,
        defaults={field:getattr(item, field) for field in [*SP_PRICES, 'stock'] if not getattr(item, field) is None})
      item.delete()
      continue



def get_df_sheet_names(pk):
  '''
    Возвращает названия листов для файла настройки если он есть\\
    В противном случае None
  '''
  file = None
  if not SupplierFile.objects.filter(setting=pk).first(): return None
  file = SupplierFile.objects.filter(setting=pk).first().file
  if not file: return None
  columns = pd.ExcelFile(file, engine='calamine').sheet_names
  file.close()
  return columns

def get_df(pk, nrows: int | None = 100)->pd.DataFrame|None:
  '''
    Возвращает pd.Dataframe из файла настройки если он есть\\
    В противном случае None
  '''
  file = None
  setting = Setting.objects.get(pk=pk)
  if not SupplierFile.objects.filter(setting=pk).first(): return None
  file = SupplierFile.objects.filter(setting=pk).first().file
  if not file: return None
  df = pd.read_excel(file, engine='calamine', dtype=str, sheet_name=setting.sheet_name, nrows=nrows, index_col=None).dropna(axis=0, how='all').dropna(axis=1, how='all')
  file.close()
  if df.shape[0] == 0:
    return None
  return df

def get_dictformset(post, pk, link):
  '''
    Менеджер для форм замены в настройке
  '''
  mlink = Link.objects.get_or_create(setting=pk, key=link)[0]
  return DictFormset(
          post if post else None,
          initial=[
            {'key': ldict.key, 'value': ldict.value}
            for ldict in mlink.dicts.all()
          ],
          form_kwargs={'link':link, 'pk':pk},
          prefix=f'{link}-dict'
        )
  

def get_linkformset(post, pk):
  '''
    Менеджер для форм на заголовки столбцов таблицы
  '''
  df = get_df(pk)
  if df is None: return None
  setting = Setting.objects.get(pk=pk)
  return LinkFormset(
      post if post else None, 
      initial=[
          {
            'key': 
            Link.objects.filter(setting=setting, value=column).first().key 
            if Link.objects.filter(setting=setting, value=column).exists()
            else None
          }

          for column in df.columns
        ],
      prefix='link', 
      form_kwargs=
        {
          'columns':df.columns
        }
      )


def get_indicts(post, pk):
  '''
    Менеджер форм значений для пустых ячеек таблицы
  '''
  indicts = dict()
  for link, name in LINKS.items():
    if link == '': continue
    mlink = Link.objects.get_or_create(setting=Setting.objects.get(pk=pk), key=link)[0]
    dict_formset = DictFormset(
          post if post else None,
          initial=[
            {'key': ldict.key, 'value': ldict.value}
            for ldict in mlink.dicts.all()
          ],
          form_kwargs={'link':link, 'pk':pk},
          prefix=f'{link}-dict'
        )
    initial = InitialForm(post, initial=mlink.initial, prefix=f'{link}-initial', pk=pk)
    indicts[link] = (initial, dict_formset)
    if post and dict_formset.is_valid() and post.get('action'):
      action = post.get('action')
      if 'delete-' + link in action:
        data = []
        for i in range(len(dict_formset.cleaned_data)):
          if not i == int(action.strip(f'delete-{link}-dict-')):
            data.append(dict_formset.cleaned_data[i])
        dict_formset = DictFormset(initial=data,
                        form_kwargs={'link':link, 'pk':pk},
                        prefix=f'{link}-dict')
      elif 'add-' + link in action:
        data = dict_formset.cleaned_data
        data.append({})
        dict_formset = DictFormset(initial=data,
                        form_kwargs={'link':link, 'pk':pk},
                        prefix=f'{link}-dict')
    indicts[link] = { 
        'verbose_name':name, 
        'initial':initial, 
        'dict_formset':dict_formset,
        }
  return indicts


def load_setting(pk):
  '''
    Возвращает обработанные товары ПП\\
    Если не найден файл возвращает None
  '''
  setting = Setting.objects.get(pk=pk)
  links = Link.objects.filter(setting=setting)
  df = get_df(pk, nrows=None)
  sps = SupplierProduct.objects.filter(supplier=setting.supplier)
  s_articles = sps.values_list('article', flat=True)
  s_names = sps.values_list('name', flat=True)
  if not links.filter(Q(value__isnull=False)).exists():
    return None
  for link in links:
    if link.value == '' or link.value is None: continue
    print(link.key, df[link.value])
    df[link.value] = df[link.value].str.replace(r'\s+', ' ', regex=True)
    if link.initial:
      df[link.value] = df[link.value].fillna(link.initial)
    for dict in link.dicts.all():
      df[link.value] = df[link.value].replace(dict.key, dict.value)
    df = df.rename(columns={link.value : link.key})
  if not 'article' in df.columns: return None

  df = df.replace('', pd.NA)
  df = df.loc[:,[link.key for link in links if not link.key=='' and link.key in df.columns]]
  df = df.dropna(subset=['article'])
  for link in links:
    if link.key in df.columns and link.key in SP_NUMBERS:
      df[link.key] = pd.to_numeric(df[link.key], errors='coerce')
  df = df.dropna(subset=[link.key for link in links if not link.key=='article' and link.key in df.columns], how='all')
  if not 'name' in df.columns:
    _df = df.copy()
    names = _df['article'].apply(lambda article: sps.filter(article=article).values_list('name', flat=True))
    _df['name'] = names
    _df = _df[_df['name'].apply(len) > 0]
    _df = _df.explode('name', ignore_index=True)
    df = _df
  df = df.dropna(subset=['name'])

  df = df.replace({pd.NA: None, float('nan'): None, '': None})
  
  if not setting.create_new:
    df = df[df['name'].isin(s_names) & df['article'].isin(s_articles)]
  df.drop_duplicates(subset=['article', 'name'], keep='first')
  if 'manufacturer' in df.columns:
    df['manufacturer'] = df['manufacturer'].apply(lambda s: Manufacturer.objects.get_or_create(name=s)[0] if s else None)
  if 'discount' in df.columns:
    df['discount'] = df['discount'].apply(lambda s: Discount.objects.get_or_create(supplier=setting.supplier, name=s)[0] if s else None)
  print(df['article'], df.dtypes)
  def get_spmodel(row):
    data = {
        link.key: Decimal(str(getattr(row, link.key))) if link.key in SP_NUMBERS else getattr(row, link.key)
        for link in links 
        if not link.key=='article' and not link.key == 'name' and link.key in df.columns
        and getattr(row, link.key)
      }
    return SupplierProduct(
      supplier=setting.supplier,
      article=row.article,
      name=row.name,
      **data)
  sp_model_instances = map(get_spmodel, df.itertuples(index=False))
  sp_update_fields = [link.key for link in links if not link.key=='article' and not link.key == 'name' and link.key in df.columns]
  sp_update_fields.append('updated_at')
  sps = SupplierProduct.objects.bulk_create(
    sp_model_instances, 
    update_conflicts=True, 
    update_fields=sp_update_fields,
    unique_fields=['supplier', 'article', 'name'])
  if 'stock' in df.columns:
    setting.supplier.stock_updated_at = timezone.now()
  if not set(SP_PRICES).intersection(set(df.columns)) == set():
    setting.supplier.price_updated_at = timezone.now()
  setting.supplier.save()
  return sps


