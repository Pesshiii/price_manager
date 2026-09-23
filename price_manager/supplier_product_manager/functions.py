
from django.utils import timezone
from django.db import transaction
from django.db.models import ExpressionWrapper, Q, BooleanField, Value
from django.core.cache import cache
from django.conf import settings

from .models import (SupplierFile, Setting, Link, 
                     SupplierProduct, Discount,
                     SP_NUMBERS, SP_PRICES)
from .tables import SP_AVAILABLE_COLUMN_MAP, SP_DEFAULT_VISIBLE_COLUMNS
from main_product_manager.models import MainProduct

from .forms import (DictFormset, LinkFormset,
                    InitialForm,
                    LINKS,)
from dataclasses import dataclass, field

import pandas as pd
import numpy as np
from decimal import Decimal
import re
import hashlib
import json
import logging

SPS_CACHE_TTL_SECONDS = 60 * 30
CACHE_TTL = 60 * 60 * 24 * 30  # 30 дней
# 1.1: без category и manufacturer (Phase 2b). Смена версии меняет ключ кэша
# get_sps, так что разбор, закэшированный до удаления колонок, не всплывёт.
# 1.2: в кэше лежит {'payload', 'stats'}, а не голый список.
# 1.3: в stats появились article_conflicts и article_conflict_examples.
SPS_JSON_SCHEMA_VERSION = "1.3"
# Счётчики разбора, которые get_sps_result отдаёт вместе с payload, по этапам.
SPS_STAT_FIELDS = (
    "rows_in_sheet",      # непустые строки листа
    "rows_with_article",  # из них с артикулом
    "rows_with_values",   # из них хоть одно значение распозналось
    "article_conflicts",  # артикулов, которые в файле встречаются с разными названиями
    "rows_without_name",  # отброшены: нет названия
    "rows_unmatched",     # отброшены: не совпали с товарами поставщика (create_new выключен)
    "duplicates",         # отброшены: повтор артикула и названия в файле (взята первая строка)
    "covered",            # будут записаны
    "covered_price",      # из них с ценой
    "covered_stock",      # из них с остатком
)
SPS_JSON_FIELDS = (
    "article",
    "name",
    "description",
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
    "discount": ("discount", "скидка", "группа скидок"),
    "stock": ("stock", "остаток", "количество", "наличие", "qty"),
    "supplier_price": ("supplierprice", "supplier_price", "цена", "цена поставщика", "закупочная цена", "price"),
    "rrp": ("rrp", "ррц", "розничная цена"),
    "discount_price": ("discountprice", "discount_price", "цена со скидкой", "скидочная цена"),
}


class SupplierFileStorageMissingError(FileNotFoundError):
  """Файл настройки отсутствует в storage backend."""


class SupplierImportError(Exception):
  """Файл нельзя импортировать по этой настройке; сообщение — причина для пользователя."""

  def __init__(self, *args):
    super().__init__(*args)
    # Parse counters gathered before the refusal; get_sps_result fills them in.
    self.stats: dict = {}


def _format_columns(columns, limit: int = 15) -> str:
  shown = ', '.join(f'«{column}»' for column in columns[:limit])
  if len(columns) > limit:
    shown += f' и ещё {len(columns) - limit}'
  return shown or 'нет'


def _empty_result_reason(setting, rows_with_article: int, rows_with_values: int) -> str:
  if rows_with_article == 0:
    return 'В столбце артикула нет ни одного значения — проверьте ряд заголовков и сопоставление столбцов'
  if rows_with_values == 0:
    return (f'Строк с артикулом: {rows_with_article}, но ни в одной нет значений '
            'в сопоставленных столбцах (цена, остаток и т. п.)')
  if not setting.create_new:
    match_by = 'артикулу и названию' if setting.links.filter(key='name').exclude(value__isnull=True).exclude(value='').exists() else 'артикулу'
    return (f'Ни одна из {rows_with_values} строк файла не совпала с товарами поставщика по {match_by}. '
            'Добавление новых товаров выключено — включите его или проверьте столбцы артикула и названия')
  return f'Ни у одной из {rows_with_values} строк файла нет названия'


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
    # Longest alias wins, not first declared: "цена" is a substring of
    # "ценасоскидкой", so declaration order alone would let supplier_price
    # claim a "Цена со скидкой, руб" column ahead of discount_price.
    best_key, best_alias_length = None, 0
    for key, aliases in alias_map.items():
      if key in used_keys:
        continue
      longest = max((len(alias) for alias in aliases if alias and alias in column_name), default=0)
      if longest > best_alias_length:
        best_key, best_alias_length = key, longest
    if best_key is not None:
      detected_keys[idx] = best_key
      used_keys.add(best_key)

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

def _df_cache_key(setting: Setting, supplier_file: SupplierFile) -> str:
  # The instance's sheet_name and index_row, not the class attribute: keyed on
  # `Setting.sheet_name` every sheet shared one entry, so switching the sheet
  # kept serving the old sheet's columns until the entry expired.
  return (f'setting<{setting.pk}>::dataframe<{supplier_file.pk}>'
          f'::sheet<{setting.sheet_name}>::row<{setting.index_row}>')

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
  if not settings.DEBUG:
    cached_df=cache.get(_df_cache_key(setting, sf))
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
  if not settings.DEBUG:
    cache.set(_df_cache_key(setting, sf), df, timeout=60*30)
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



def get_sps(setting_or_pk: Setting | int, recache: bool = False) -> list[dict]:
    """
    Возвращает каноничные товары поставщика в JSON-виде:
    required: article(str), name(str)
    optional: description(str|null), discount(str|null),
              stock(int|null), supplier_price(str|null), rrp(str|null), discount_price(str|null)

    Никогда не возвращает пустой результат: если импортировать нечего,
    выбрасывает SupplierImportError с причиной для пользователя.
    """
    return get_sps_result(setting_or_pk, recache=recache)[0]


def get_sps_result(setting_or_pk: Setting | int, recache: bool = False) -> tuple[list[dict], dict]:
    """
    То же, что get_sps, плюс счётчики разбора по этапам (см. SPS_STAT_FIELDS).

    Счётчики кэшируются вместе с payload. SupplierImportError несёт в .stats
    те счётчики, что успели накопиться до отказа.
    """
    setting = (
        setting_or_pk
        if isinstance(setting_or_pk, Setting)
        else Setting.objects.get(pk=setting_or_pk)
    )
    signature = _get_setting_signature(setting)
    cache_key = _get_sps_cache_key(setting, signature)
    if not settings.DEBUG and not recache:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached['payload'], cached['stats']

    links = Link.objects.filter(setting=setting)
    stats = {
        'mapped_keys': sorted(
            links.filter(Q(value__isnull=False) & ~Q(value='') | Q(initial__isnull=False) & ~Q(initial=''))
            .values_list('key', flat=True)
        ),
    }
    try:
        payload = _parse_sps(setting, links, stats)
    except SupplierImportError as exc:
        exc.stats = stats
        raise
    if not settings.DEBUG:
        cache.set(cache_key, {'payload': payload, 'stats': stats}, timeout=SPS_CACHE_TTL_SECONDS)
    return payload, stats


def _parse_sps(setting: Setting, links, stats: dict) -> list[dict]:
    df = get_df(setting.pk)
    sps = SupplierProduct.objects.filter(supplier=setting.supplier)
    s_values = map(tuple, sps.values_list('article', 'name'))
    resolve_conflicts(sps)
    if df is None:
        if not setting.supplierfiles.exists():
            raise SupplierImportError('Для настройки не загружен файл')
        raise SupplierImportError(
            f'Лист «{setting.sheet_name}» пуст'
            + (f' начиная со строки {setting.index_row}' if setting.index_row else '')
            + ' — проверьте лист и ряд заголовков')
    stats['rows_in_sheet'] = len(df)
    if not links.filter(Q(value__isnull=False) | Q(initial__isnull=False)).exists():
        raise SupplierImportError('Не сопоставлен ни один столбец файла')
    file_columns = list(df.columns)
    for link in links:
        if link.value == '' or link.value is None:
            if link.initial == '' or link.initial is None:
                continue
            df[link.key] = link.initial
        elif link.value in df.columns:
            df = df.rename(columns={link.value: link.key})
            if not link.initial == '' and not link.initial is None:
                df[link.key] = df[link.key].fillna(link.initial)
        elif not link.initial == '' and not link.initial is None:
            # The mapped column is gone from this file; the setting's fallback
            # value still applies. (fillna on the missing column used to raise
            # a bare KeyError.)
            df[link.key] = link.initial
    if not 'article' in df.columns:
        article_link = links.filter(key='article').first()
        if article_link and article_link.value:
            raise SupplierImportError(
                f'В файле нет столбца артикула «{article_link.value}». '
                f'Столбцы в файле: {_format_columns(file_columns)}')
        raise SupplierImportError('Не указан столбец артикула')
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
    rows_with_article = stats['rows_with_article'] = len(df)
    df = df.dropna(
        subset=[link.key for link in links if not link.key == 'article' and not link.key == 'name' and link.key in df.columns],
        how='all'
    )
    rows_with_values = stats['rows_with_values'] = len(df)
    stats.update(_article_conflicts(df))
    rows_unmatched = 0

    if not 'name' in df.columns:
        if setting.create_new:
            raise SupplierImportError(
                'Для добавления новых товаров нужен столбец названия — '
                'сопоставьте его или выключите «Добавлять новые товары»')
        _df = df.copy()
        names = _df['article'].apply(lambda article: sps.filter(article=article).values_list('name', flat=True))
        _df['name'] = names
        has_names = _df['name'].apply(len) > 0
        rows_unmatched += int((~has_names).sum())
        _df = _df[has_names]
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

    rows_before = len(df)
    df = df.dropna(subset=['name'])
    stats['rows_without_name'] = rows_before - len(df)
    df = df.replace({pd.NA: None, float('nan'): None, '': None, 'NaN': None})

    if not setting.create_new:
        mask = df[['article', 'name']].apply(tuple, axis=1).isin(s_values)
        rows_unmatched += int((~mask).sum())
        df = df[mask]
    stats['rows_unmatched'] = rows_unmatched

    rows_before = len(df)
    df = df.drop_duplicates(subset=['article', 'name'], keep='first')
    stats['duplicates'] = rows_before - len(df)
    stats.update(_coverage(df))
    for required_field in SPS_JSON_REQUIRED_FIELDS:
        if required_field not in df.columns:
            raise SupplierImportError(f'После разбора нет обязательного поля «{LINKS[required_field]}»')
    if df.empty:
        raise SupplierImportError(_empty_result_reason(setting, rows_with_article, rows_with_values))
    return df.to_dict(orient="records")


ARTICLE_CONFLICT_EXAMPLES = 5


def _article_conflicts(df: pd.DataFrame) -> dict:
    """Артикулы, которые в файле встречаются с разными названиями.

    Товар определяется парой (артикул, название), так что такие строки
    загружаются как разные товары. Обычно это варианты одного товара под общим
    артикулом, но бывает и ошибка в прайсе — поэтому о них предупреждаем, а не
    отбрасываем. Считается только по названиям из файла: если названия берутся
    из базы (столбец названия не сопоставлен), файл их не задаёт.
    """
    if 'name' not in df.columns:
        return {'article_conflicts': 0, 'article_conflict_examples': []}
    names_per_article = df.groupby('article', sort=False)['name'].nunique()
    conflicting = names_per_article[names_per_article > 1]
    return {
        'article_conflicts': int(len(conflicting)),
        'article_conflict_examples': [str(a) for a in conflicting.index[:ARTICLE_CONFLICT_EXAMPLES]],
    }


def duplicate_warning(stats: dict) -> str:
    """Предупреждение о повторах в файле для уведомления об импорте; '' — если их нет."""
    parts = []
    duplicates = stats.get('duplicates') or 0
    if duplicates:
        parts.append(f'повторов строк: {duplicates} (взята первая из повторяющихся)')
    conflicts = stats.get('article_conflicts') or 0
    if conflicts:
        examples = ', '.join(stats.get('article_conflict_examples') or [])
        parts.append(
            f'артикулов с разными названиями: {conflicts}'
            + (f' (например: {examples})' if examples else '')
            + ' — загружены как разные товары')
    return ('Внимание: ' + '; '.join(parts) + '.') if parts else ''


def _coverage(df: pd.DataFrame) -> dict:
    """Сколько строк импорт запишет — всего, с ценой и с остатком.

    Цены и остатки считаются раздельно: столбец остатка может перестать
    распознаваться, пока цены грузятся как обычно, и общее число строк этого
    не покажет. Несопоставленный остаток даёт covered_stock = 0 — так же, как
    столбец, в котором не распозналось ни одно число.
    """
    price_columns = [column for column in SP_PRICES if column in df.columns]
    return {
        'covered': len(df),
        'covered_price': int(df[price_columns].notna().any(axis=1).sum()) if price_columns else 0,
        'covered_stock': int(df['stock'].notna().sum()) if 'stock' in df.columns else 0,
    }


@dataclass
class ImportOutcome:
    """Результат load_setting: записанные строки и счётчики.

    stats — счётчики разбора из get_sps_result плус счётчики применения:
    created / updated (новые и существующие строки среди записанных) и
    missing (строки поставщика, которых нет в файле; у них обнулены
    сопоставленные остаток и цены).
    """
    sps: list
    stats: dict = field(default_factory=dict)


def apply_counts(setting: Setting, payload: list[dict]) -> dict:
    """Что сделает применение payload, не применяя его: created / updated / missing.

    missing — строки поставщика, которых нет в payload; при применении у них
    очищаются сопоставленные остаток и цены. Считается до записи, чтобы
    показать это в окне подтверждения.
    """
    existing_keys = set(
        SupplierProduct.objects.filter(supplier=setting.supplier).values_list('article', 'name')
    )
    payload_keys = {(row['article'], row['name']) for row in payload}
    created = len(payload_keys - existing_keys)
    return {
        'created': created,
        'updated': len(payload_keys) - created,
        'missing': len(existing_keys - payload_keys),
    }


def load_setting(pk, parsed: tuple[list[dict], dict] | None = None) -> ImportOutcome:
    '''
        Записывает товары ПП из файла настройки\\
        Если импортировать нечего, выбрасывает SupplierImportError\\
        parsed — готовый результат get_sps_result, чтобы не разбирать файл дважды
    '''
    setting = Setting.objects.get(pk=pk)
    # Только ключи из LINKS: каждый ключ ниже становится полем SupplierProduct.
    # Ссылка на удалённое поле (category и manufacturer до Phase 2b) иначе
    # роняла бы весь импорт прайса, а не пропускалась.
    links = [link for link in Link.objects.filter(setting=setting) if link.key in LINKS]
    # get_sps raises SupplierImportError instead of returning nothing: an empty
    # result must never reach the "missing rows" update below, which would
    # clear stock and prices of every product of the supplier.
    sps_payload, parse_stats = parsed if parsed is not None else get_sps_result(setting)
    stats = dict(parse_stats)
    # All writes or none: a failure between the upsert and the clearing of
    # missing rows used to leave the supplier half-imported.
    with transaction.atomic():
        return _apply(setting, links, sps_payload, stats)


def _apply(setting: Setting, links, sps_payload: list[dict], stats: dict) -> ImportOutcome:
    df = pd.DataFrame(sps_payload)
    df = df.dropna(subset=['name'])
    df = df.replace({pd.NA: None, float('nan'): None, '': None, 'NaN': None})

    if 'discount' in df.columns:
        df['discount'] = df['discount'].apply(
            lambda s: Discount.objects.get_or_create(supplier=setting.supplier, name=s)[0] if s else None
        )

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
    
    counts = apply_counts(setting, sps_payload)
    stats['created'], stats['updated'] = counts['created'], counts['updated']

    sp_model_instances = map(get_spmodel, df.itertuples(index=False))
    sp_update_fields = [link.key for link in links if not link.key=='article' and not link.key == 'name' and link.key in df.columns]
    sp_update_fields.append('updated_at')
    sps = SupplierProduct.objects.bulk_create(
        sp_model_instances,
        update_conflicts=True,
        update_fields=sp_update_fields,
        unique_fields=['supplier', 'article', 'name'])

    missing_sps = SupplierProduct.objects.filter(supplier=setting.supplier).exclude(pk__in=map(lambda sp: sp.pk, sps))
    stats['missing'] = missing_sps.count()

    # A row that vanished from the new file has no figure at all, so the raw
    # layer stores NULL - "the supplier did not tell us" - and never a synced 0.
    # Consumers resolve that absence themselves: update_stocks() coalesces it to
    # 0 because unknown stock is not sellable, and the price rules treat a NULL
    # price as "no price" and clear the product's derived prices
    # (product_price_manager.clear_unsourced_prices). Only columns the setting
    # still maps are cleared, so deleting a Link freezes its field at the last
    # imported value.
    if 'stock' in df.columns:
        setting.supplier.stock_updated_at = timezone.now()
        missing_sps.update(stock=None)
    if not set(SP_PRICES).intersection(set(df.columns)) == set():
        setting.supplier.price_updated_at = timezone.now()
        for column in df.columns:
           if column in SP_PRICES:
              missing_sps.update(**{column:None})
    setting.supplier.save()
    return ImportOutcome(sps=sps, stats=stats)
