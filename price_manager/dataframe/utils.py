
import pandas as pd
from django.core.cache import cache

from .models import FileModel, DictItem

_CACHE_TTL = 300  # seconds


def get_sheet_names(pk):
    """Return list of (name, name) tuples for sheets in the file with the given FileModel pk."""
    cache_key = f'df_sheets_{pk}'
    cached = cache.get(cache_key)
    if cached is not None and not cached in [[('', 'Выберите лист')], [('', 'Выберите файл')], [('', '---------')]]:
        return cached

    try:
        filemodel = FileModel.objects.get(pk=pk)
    except FileModel.DoesNotExist:
        return [('', 'Выберите файл')]
    filename = filemodel.file.name.lower()
    if filename.endswith('.csv'):
        result = [('Sheet1', 'Sheet1')]
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    try:
        excel = pd.ExcelFile(filemodel.file, engine='calamine')
        result = [(name, name) for name in excel.sheet_names]
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        return [('', 'Выберите лист')]
    finally:
        filemodel.file.close()


def get_column_names(file_pk, sheet_name=None):
    """Return list of (col, col) tuples for column headers.

    Reads only the header row (nrows=0) for speed, caches the result.
    """
    cache_key = f'df_columns_{file_pk}_{sheet_name}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        filemodel = FileModel.objects.get(pk=file_pk)
    except FileModel.DoesNotExist:
        return [('', 'Выберите файл')]
    filename = filemodel.file.name.lower()
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(filemodel.file, nrows=0)
        else:
            df = pd.read_excel(
                filemodel.file,
                sheet_name=sheet_name or 0,
                nrows=0,
                engine='calamine',
            )
        result = [('', 'Не выбран')] + [(col, col) for col in df.columns]
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        return [('', 'Не выбран')]
    finally:
        filemodel.file.close()


DICT_SCHEMA = {
    "type": "array",
    "title": "Словарь замен",
    "items": {
        "type": "object",
        "keys": {
            "key": {
                "type": "string",
                "title": "Если"
            },
            "value": {
                "type": "string",
                "title": "То"
            }
        }
    },
    "minItems": 1,
    "maxItems": 20,
}


def get_json_dicts(dictitems: list[DictItem]) -> list:
    res = [{"key": dictitem.key, "value": dictitem.value} for dictitem in dictitems]
    return res if res else [{'key': '', 'value': ''}]


def read_raw_dataframe(dataframe_instance, max_rows=200):
    """Read raw file content, return a pandas DataFrame (up to max_rows rows)."""
    if not dataframe_instance.file:
        return None
    filemodel = dataframe_instance.file
    filename = filemodel.file.name.lower()
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(filemodel.file, nrows=max_rows)
        else:
            df = pd.read_excel(
                filemodel.file,
                sheet_name=dataframe_instance.sheet_name or 0,
                nrows=max_rows,
                engine='calamine',
            )
        return df
    except Exception:
        return None
    finally:
        filemodel.file.close()


def apply_link_rules(dataframe_instance, max_rows=200):
    """Apply Link/DictItem rules to the file, return transformed DataFrame (up to max_rows rows)."""
    if not dataframe_instance.file:
        return None
    links = list(dataframe_instance.links.prefetch_related('dicts', 'contenttype').all())
    if not links:
        return None
    filemodel = dataframe_instance.file
    filename = filemodel.file.name.lower()
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(filemodel.file)
        else:
            df = pd.read_excel(
                filemodel.file,
                sheet_name=dataframe_instance.sheet_name or 0,
                engine='calamine',
            )
    except Exception:
        return None
    finally:
        filemodel.file.close()

    for link in links:
        col_name = link.contenttype.name
        if not link.value:
            if link.initial:
                df[col_name] = link.initial
        else:
            if link.value in df.columns:
                df = df.rename(columns={link.value: col_name})
                if link.initial:
                    df[col_name] = df[col_name].fillna(link.initial)
        if col_name in df.columns:
            for dictitem in link.dicts.all():
                df[col_name] = df[col_name].astype(str).str.replace(
                    dictitem.key, dictitem.value, regex=False
                )

    output_cols = [
        link.contenttype.name for link in links
        if link.contenttype.name in df.columns
    ]
    if not output_cols:
        return None
    return df[output_cols].head(max_rows)