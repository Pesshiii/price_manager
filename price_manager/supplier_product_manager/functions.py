
from django.utils import timezone
from django.db.models import ExpressionWrapper, Q, BooleanField, Value
from django.core.cache import cache

from .models import (SupplierFile, Setting, Link, 
                     SupplierProduct, Manufacturer, Discount, Category,
                     SP_NUMBERS, SP_PRICES)
from .tables import SP_AVAILABLE_COLUMN_MAP, SP_DEFAULT_VISIBLE_COLUMNS
from main_product_manager.models import MainProduct
from main_product_manager.functions import recalculate_search_vectors

from .forms import (DictFormset, LinkFormset,
                    InitialForm,
                    LINKS,)
from price_manager.settings import DEBUG
import pandas as pd
import numpy as np
from decimal import Decimal
import re
import hashlib
import json
import logging

SPS_CACHE_TTL_SECONDS = 60 * 30
CACHE_TTL = 60 * 60 * 24 * 30  # 30 дней
SPS_JSON_SCHEMA_VERSION = "1.0"
SPS_JSON_FIELDS = (
    "article",
    "name",
    "description",
    "category",
    "manufacturer",
    "discount",
    "stock",
    "supplier_price",
    "rrp",
    "discount_price",
)
SPS_JSON_REQUIRED_FIELDS = ("article", "name")

logger = logging.getLogger(__name__)


def _cache_key(user_id: int) -> str:
  return f"supplierdetail:selected_columns:user:{user_id}"


def normalize_columns(columns):
  valid = [column for column in columns if column in SP_AVAILABLE_COLUMN_MAP]
  return valid or SP_DEFAULT_VISIBLE_COLUMNS


def save_user_sp_columns(user, columns):
  normalized_columns = normalize_columns(columns)
  if not user.is_authenticated:
    return normalized_columns
  cache.set(_cache_key(user.id), normalized_columns, CACHE_TTL)
  return normalized_columns


def load_user_sp_columns(user):
  if not user.is_authenticated:
    return SP_DEFAULT_VISIBLE_COLUMNS
  return cache.get(_cache_key(user.id), SP_DEFAULT_VISIBLE_COLUMNS)

AUTO_LINK_ALIASES = {
    "article": ("article", "артикул", "код", "sku", "vendorcode"),
    "name": ("name", "название", "наименование", "товар"),
    "description": ("description", "описание"),
    "category": ("category", "категория", "группа", "раздел"),
    "manufacturer": ("manufacturer", "brand", "бренд", "производитель"),
    "discount": ("discount", "скидка", "группа скидок"),
    "stock": ("stock", "остаток", "количество", "наличие", "qty"),
    "supplier_price": ("supplierprice", "supplier_price", "цена поставщика", "закупочная цена", "price"),
    "rrp": ("rrp", "ррц", "розничная цена"),
    "discount_price": ("discountprice", "discount_price", "цена со скидкой", "скидочная цена"),
}


class SupplierFileStorageMissingError(FileNotFoundError):
  """Файл настройки отсутствует в storage backend."""


def _normalize_column_name(value: str | None) -> str:
  if value is None:
    return ""
  normalized = re.sub(r"[\W_]+", "", str(value).strip().lower())
  return normalized


def auto_detect_link_keys(columns) -> list[str | None]:
  """
  Возвращает список ключей LINK для списка столбцов.
  Один ключ назначается не более одного раза.
  """
  normalized_columns = [_normalize_column_name(column) for column in columns]
  detected_keys: list[str | None] = [None] * len(normalized_columns)
  used_keys: set[str] = set()

  alias_map = {
    key: {_normalize_column_name(alias) for alias in aliases if alias}
    for key, aliases in AUTO_LINK_ALIASES.items()
  }

  for key, verbose_name in LINKS.items():
    if key == "":
      continue
    alias_map.setdefault(key, set()).add(_normalize_column_name(verbose_name))
    alias_map[key].add(_normalize_column_name(key))

  for idx, column_name in enumerate(normalized_columns):
    if not column_name:
      continue
    for key, aliases in alias_map.items():
      if key in used_keys:
        continue
      if column_name in aliases:
        detected_keys[idx] = key
        used_keys.add(key)
        break

  for idx, column_name in enumerate(normalized_columns):
    if detected_keys[idx] is not None or not column_name:
      continue
    for key, aliases in alias_map.items():
      if key in used_keys:
        continue
      if any(alias and alias in column_name for alias in aliases):
        detected_keys[idx] = key
        used_keys.add(key)
        break

  return detected_keys

def resolve_conflicts(qs):
  def resolve(item):
    cl_name = re.sub(r'\s', ' ', item.name)
    if cl_name == item.name:
      return item
    return SupplierProduct.objects.get_or_create(
        supplier = item.supplier, 
        article=item.article, 
        name=cl_name,
        defaults={field:getattr(item, field) for field in [*SP_PRICES, 'stock'] if not getattr(item, field) is None})[0]
  return list(map(resolve, qs))



def get_df_sheet_names(pk):
  '''
    Возвращает названия листов для файла настройки если он есть\\
    В противном случае None
  '''
  file = None
  sf = SupplierFile.objects.filter(setting=pk).order_by('-pk').first()
  if not sf: return None
  file = sf.file
  if not file: return None
  columns = pd.ExcelFile(file, engine='calamine').sheet_names
  file.close()
  return columns

def get_df(pk, recache=False)->pd.DataFrame|None:
  '''
    Возвращает pd.Dataframe из файла настройки если он есть\\
    В противном случае None
  '''
  file = None
  try:
    setting = Setting.objects.get(pk=pk)
  except:
    return None
  sf = SupplierFile.objects.filter(setting=pk).order_by('-pk').first()
  if not sf: return None
  validated_file = sf.file
  if not validated_file or not validated_file.name:
    return None
  if not validated_file.storage.exists(validated_file.name):
    logger.error(
      "Supplier file is missing in storage (setting_id=%s, file_name=%s)",
      pk,
      validated_file.name,
    )
    raise SupplierFileStorageMissingError(
      f"Файл настройки отсутствует в media-хранилище: setting_id={pk}, file={validated_file.name}"
    )
  if not DEBUG:
    cached_df=cache.get(f'setting<{pk}>::dataframe<{sf.pk}>::<{Setting.sheet_name}>')
    if not recache and not cached_df is None:
        return cached_df
  validated_file.open('rb')
  try:
    df = pd.read_excel(validated_file, engine='calamine', dtype=str, skiprows=setting.index_row, sheet_name=setting.sheet_name, index_col=None, na_values=['']).dropna(axis=0, how='all').dropna(axis=1, how='all')
  finally:
    validated_file.close()
  for column in df.columns:
    df[column] = df[column].str.replace(r'\s+', ' ', regex=True)
  if df.shape[0] == 0:
    return None
  if not DEBUG:
    cache.set(f'setting<{pk}>::dataframe<{sf.pk}>::<{Setting.sheet_name}>', df, timeout=60*30)
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
    initial = InitialForm(post if post else None, initial={'initial':mlink.initial}, prefix=f'{link}-initial', pk=pk)
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


def _get_setting_signature(setting: Setting) -> str:
    supplier_file = setting.supplierfiles.order_by("-pk").first()
    links = (
        setting.links.prefetch_related("dicts")
        .all()
        .order_by("key", "value", "initial", "pk")
    )
    payload = {
        "setting": {
            "id": setting.pk,
            "sheet_name": setting.sheet_name,
            "ignore_name": setting.ignore_name,
            "create_new": setting.create_new,
            "index_row": setting.index_row,
        },
        "supplier_file": {
            "id": supplier_file.pk if supplier_file else None,
            "name": supplier_file.file.name if supplier_file and supplier_file.file else None,
            "size": supplier_file.file.size if supplier_file and supplier_file.file else None,
        },
        "links": [
            {
                "key": link.key,
                "value": link.value,
                "initial": link.initial,
                "dicts": list(
                    link.dicts.all().order_by("key", "value", "pk").values_list("key", "value")
                ),
            }
            for link in links
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _get_sps_cache_key(setting: Setting, signature: str) -> str:
    return f"setting<{setting.pk}>::sps::v<{SPS_JSON_SCHEMA_VERSION}>::sig<{signature}>"


def _to_canonical_sps(df: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    for row in df.to_dict(orient="records"):
        item = {field: row.get(field) for field in SPS_JSON_FIELDS}
        records.append(item)
    return records


def get_sps(setting_or_pk: Setting | int, recache: bool = False) -> list[dict] | None:
    """
    Возвращает каноничные товары поставщика в JSON-виде:
    required: article(str), name(str)
    optional: description(str|null), category(str|null), manufacturer(str|null), discount(str|null),
              stock(int|null), supplier_price(str|null), rrp(str|null), discount_price(str|null)
    """
    setting = (
        setting_or_pk
        if isinstance(setting_or_pk, Setting)
        else Setting.objects.get(pk=setting_or_pk)
    )
    signature = _get_setting_signature(setting)
    cache_key = _get_sps_cache_key(setting, signature)
    if not DEBUG and not recache:
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return cached_payload

    links = Link.objects.filter(setting=setting)
    df = get_df(setting.pk)
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
            if not link.initial == '' and not link.initial is None:
                df[link.key] = df[link.key].fillna(link.initial)
    if not 'article' in df.columns:
        return None
    for link in links:
        if not link.key in df.columns:
            continue
        for dict in link.dicts.all():
            df[link.key] = df[link.key].str.replace(dict.key, dict.value)
            df = df.loc[:, [link.key for link in links if not link.key == '' and link.key in df.columns]]
        if link.key in df.columns and link.key in SP_NUMBERS:
            df[link.key] = df[link.key].str.replace(',', '.')
            df[link.key] = pd.to_numeric(df[link.key], errors='coerce')
            df[link.key] = df[link.key].apply(lambda val: val if val >= 0 else None)

    df = df.dropna(subset=['article'])
    df = df.dropna(
        subset=[link.key for link in links if not link.key == 'article' and not link.key == 'name' and link.key in df.columns],
        how='all'
    )

    if not 'name' in df.columns:
        if setting.create_new:
            return None
        _df = df.copy()
        names = _df['article'].apply(lambda article: sps.filter(article=article).values_list('name', flat=True))
        _df['name'] = names
        _df = _df[_df['name'].apply(len) > 0]
        _df = _df.explode('name', ignore_index=True)
        df = _df

    if setting.create_new and setting.ignore_name:
        _df = df.copy()
        names = _df['article'].apply(lambda article: sps.filter(article=article).values_list('name', flat=True))
        _df['names_indb'] = names
        _df = _df.explode('names_indb', ignore_index=True)
        _df['name'] = _df['names_indb'].fillna(_df['name'])
        _df.drop('names_indb', axis=1)
        df = _df

    df = df.dropna(subset=['name'])
    df = df.replace({pd.NA: None, float('nan'): None, '': None, 'NaN': None})

    if not setting.create_new:
        mask = df[['article', 'name']].apply(tuple, axis=1).isin(s_values)
        df = df[mask]

    df = df.drop_duplicates(subset=['article', 'name'], keep='first')
    for required_field in SPS_JSON_REQUIRED_FIELDS:
        if required_field not in df.columns:
            return None
    payload = _to_canonical_sps(df)
    if not DEBUG:
        cache.set(cache_key, payload, timeout=SPS_CACHE_TTL_SECONDS)
    return payload


def load_setting(pk):
    '''
        Возвращает обработанные товары ПП\\
        Если не найден файл возвращает None
    '''
    setting = Setting.objects.get(pk=pk)
    links = Link.objects.filter(setting=setting)
    sps_payload = get_sps(setting)
    if sps_payload is None:
        return None
    df = pd.DataFrame(sps_payload)
    df = df.dropna(subset=['name'])
    df = df.replace({pd.NA: None, float('nan'): None, '': None, 'NaN': None})

    if 'manufacturer' in df.columns:
        df['manufacturer'] = df['manufacturer'].apply(
            lambda s: Manufacturer.objects.get_or_create(name=s)[0] if s else None
        )
    if 'discount' in df.columns:
        df['discount'] = df['discount'].apply(
            lambda s: Discount.objects.get_or_create(supplier=setting.supplier, name=s)[0] if s else None
        )
    if 'category' in df.columns:
        def _get_category(value):
            if not value:
                return None
            parts = [p.strip() for p in str(value).split(">") if p and str(p).strip()]
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
            link.key: Decimal(str(getattr(row, link.key))) if link.key in SP_PRICES else getattr(row, link.key)
            for link in links 
            if not link.key=='article' and not link.key == 'name' and link.key in df.columns
            and getattr(row, link.key) is not None
        }
        return SupplierProduct(
            supplier=setting.supplier,
            article=row.article,
            name=row.name,
            **data
            )
    
    sp_model_instances = map(get_spmodel, df.itertuples(index=False))
    sp_update_fields = [link.key for link in links if not link.key=='article' and not link.key == 'name' and link.key in df.columns]
    sp_update_fields.append('updated_at')
    sps = SupplierProduct.objects.bulk_create(
        sp_model_instances,
        update_conflicts=True,
        update_fields=sp_update_fields,
        unique_fields=['supplier', 'article', 'name'])

    missing_sps = SupplierProduct.objects.filter(supplier=setting.supplier).exclude(pk__in=map(lambda sp: sp.pk, sps))

    if 'stock' in df.columns:
        setting.supplier.stock_updated_at = timezone.now()
        missing_sps.update(stock=0)
    if not set(SP_PRICES).intersection(set(df.columns)) == set():
        setting.supplier.price_updated_at = timezone.now()
        for column in df.columns:
           if column in SP_PRICES:
              missing_sps.update(**{column:0})
    setting.supplier.save()
    return sps
