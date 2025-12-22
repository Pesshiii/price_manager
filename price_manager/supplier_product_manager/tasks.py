from procrastinate.contrib.django import app
from django.utils import timezone
from django.contrib.postgres.search import SearchVector
from django.db.models import Value

import pandas as pd
from decimal import Decimal
import logging
import re

from .models import (SupplierFile, SupplierProduct,
                     Setting, Link, Dict,
                     SP_FKS, SP_INTEGERS, SP_NUMBERS, SP_PRICES, LINKS)
from supplier_manager.models import Category, Manufacturer
from main_product_manager.models import MainProduct


logger = logging.getLogger('procrastinate')

def clean_headers(df):
  """Clean headers from unwanted characters"""
  df.columns = [re.sub(r'[\r\n\t]', '', str(col)) for col in df.columns]
  return df


def get_safe(value, type=None):
  if not type: return value
  if value == '': return value
  if type == int:
    return int(value)
  if type == float:
    return float(value)
  return value


def convert_sp(value, field):
  if field in SP_PRICES:
    if not value or  value == '':
      num = 0
    else:
      num = get_safe(value, Decimal)
    return 0 if num < 0 else num
  if field in SP_INTEGERS:
    if not value or  value == '':
      num = 0
    else:
      num = get_safe(value, int)
    return 0 if num < 0 else num
  return value



def clean_column(column):
  column = column.str.strip()

  # Remove special characters
  column = column.str.replace(r'[^\w\s]', '', regex=True)

  # Replace multiple spaces with single space
  column = column.str.replace(r'\s+', ' ', regex=True)
  return column


def get_df(df: pd.DataFrame, links, initials, dicts, setting:Setting):
  for column, field in links.items():
    if not column in df.columns:
      df[column] = None
    if field == 'article':
      df=df[df[column].notnull()]
    if field == 'name' and setting.differ_by_name:
      df=df[df[column].notnull()]
    if field in SP_PRICES and setting.priced_only:
      df = df[df[column].notnull()]
    buf: pd.Series = df[column]
    buf = buf.fillna(initials[field])
    buf = buf.astype(str)
    buf = buf.replace(dicts[field], regex=True)
    df[column] = buf
  return df

def get_upload_data(setting: Setting, df: pd.DataFrame):
  links = {link.value: link.key for link in Link.objects.filter(setting=setting)}
  initials = {link.key: link.initial if link.initial else '' for link in Link.objects.filter(setting=setting)}
  dicts = {link.key: {item.key: item.value for item in Dict.objects.filter(link=link)} for link in Link.objects.filter(setting=setting)}
  for key, value in LINKS.items():
    if key == '': continue
    buf = value
    if key not in links.values():
      if not key in initials or initials[key] == '': continue
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

def upload_from_df(sfile: SupplierFile):
  logs = []
  try:
    setting = sfile.setting
    supplier = setting.supplier
    df = pd.read_excel(sfile.file, sheet_name=setting.sheet_name).dropna(axis=0, how='all').dropna(axis=1, how='all')
    df = clean_headers(df)
    sfile.file.close()
    df, links, initials, dicts = get_upload_data(setting, df)
    rev_links = {value: key for key, value in links.items()}

    mps = []
    sps = []
    
    cats = {}
    if 'category' in rev_links:
      df[rev_links['category']] = clean_column(df[rev_links['category']])
      cats = {cat: Category.objects.get_or_create(name=cat)[0] for cat in df[rev_links['category']].unique()}
    mans = {}
    if 'manufacturer' in rev_links:
      df[rev_links['manufacturer']] = clean_column(df[rev_links['manufacturer']])
      mans = {man: Manufacturer.objects.get_or_create(name=man)[0] for man in df[rev_links['manufacturer']].unique()}
  except BaseException as ex:
    sfile.status = -1
    logs.append(f'Фатальная ошибка: {ex}')
    sfile.logs = '\n'.join(logs)
    sfile.save()
    return

  for _, row in df.iterrows():
    product = SupplierProduct(supplier=supplier, article=row[rev_links['article']], name=row[rev_links['name']])
    for column, field in links.items():
      if field in SP_FKS:
        if field == 'category':
          setattr(product, field, cats[row[column]])
        elif field == 'manufacturer':
          setattr(product, field, mans[row[column]])
        continue
      try:
        if field in SP_NUMBERS:
          setattr(product, field, Decimal(row[column]))
        else:
          setattr(product, field, row[column])
      except BaseException as ex:
        logs.append(f'Ошибка: {ex}, {row[column]}')
    if setting.update_main:
      main_product = MainProduct(supplier=supplier, article=product.article, name=product.name)
      if 'category' in rev_links:
        main_product.category = product.category
      if 'manufacturer' in rev_links:
        main_product.manufacturer = product.manufacturer
      text = main_product._build_search_text()
      main_product.search_vector = SearchVector(Value(text), config='russian')
      product.main_product = main_product
      mps.append(main_product)
    sps.append(product)
  try:
    MainProduct.objects.bulk_create(mps, update_conflicts=True, unique_fields=['supplier', 'article', 'name'], update_fields=['search_vector', 'manufacturer'])
    update_fields = [field for field in links.values() if not field=='discounts']
    update_fields.extend(['main_product'])
    sps = SupplierProduct.objects.bulk_create(sps, update_conflicts=True, unique_fields=['supplier', 'article', 'name'], update_fields=update_fields)
    for price in SP_PRICES:
      if price in rev_links:
        supplier.price_updated_at = timezone.now()
    if 'stock' in rev_links:
      supplier.stock_updated_at = timezone.now()
    supplier.save()
    sfile.status = 1
    logs.append(f'Загрузка завершена')
    sfile.logs = '\n'.join(logs)
    sfile.save()
  except BaseException as ex:
    sfile.status = -1
    logs.append(f'Фатальная ошибка: {ex}')
    sfile.logs = '\n'.join(logs)
    sfile.save()





@app.task
def upload_supplier_files():
  sfiles = SupplierFile.objects.all()
  for sfile in sfiles:
    if sfile.status == 0:
      upload_from_df(sfile)