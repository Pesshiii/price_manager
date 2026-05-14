
import pandas as pd
from django.core.cache import cache

from .models import FileModel, DictItem

_CACHE_TTL = 300  # seconds


def get_sheet_names(pk):
    """Return list of (name, name) tuples for sheets in the file with the given FileModel pk."""
    cache_key = f'df_sheets_{pk}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        filemodel = FileModel.objects.get(pk=pk)
    except FileModel.DoesNotExist:
        return [('', 'Выберите лист')]
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


def get_column_names(file_pk, sheet_name=None, index_row=None):
    """Return list of (col, col) tuples for column headers.

    Reads only the header row (nrows=0) for speed, caches the result.
    """
    cache_key = f'df_columns_{file_pk}_{sheet_name}_{index_row}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        filemodel = FileModel.objects.get(pk=file_pk)
    except FileModel.DoesNotExist:
        return [('', '---------')]
    filename = filemodel.file.name.lower()
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(filemodel.file, nrows=0, skiprows=index_row)
        else:
            df = pd.read_excel(
                filemodel.file,
                sheet_name=sheet_name or 0,
                nrows=0,
                skiprows=index_row,
                engine='calamine',
            )
        result = [('', '---------')] + [(col, col) for col in df.columns]
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        return [('', '---------')]
    finally:
        filemodel.file.close()


DICT_SCHEMA = {
    "type": "array",
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
    "minItems": 0,
    "maxItems": 20,
}


def get_json_dicts(dictitems: list[DictItem]) -> list:
    res = [{"key": dictitem.key, "value": dictitem.value} for dictitem in dictitems]
    return res if res else [{'key': '', 'value': ''}]


def _safe_file(dataframe_instance):
    """Return the FileModel attached to a Dataframe, or None.

    Wraps FK access in try/except so a stale file_id (pointing at a deleted
    FileModel row) doesn't raise FileModel.DoesNotExist.
    """
    try:
        return dataframe_instance.file
    except FileModel.DoesNotExist:
        return None


def read_raw_dataframe(dataframe_instance, max_rows=200):
    """Read raw file content, return a pandas DataFrame (up to max_rows rows)."""
    filemodel = _safe_file(dataframe_instance)
    if filemodel is None:
        return None
    filename = filemodel.file.name.lower()
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(filemodel.file, nrows=max_rows, skiprows=dataframe_instance.index_row)
        else:
            df = pd.read_excel(
                filemodel.file,
                sheet_name=dataframe_instance.sheet_name or 0,
                nrows=max_rows,
                skiprows=dataframe_instance.index_row,
                engine='calamine',
            )
        return df
    except Exception:
        return None
    finally:
        filemodel.file.close()


def apply_link_rules(dataframe_instance, max_rows=200):
    """Apply Link/DictItem rules to the file, return transformed DataFrame (up to max_rows rows)."""
    filemodel = _safe_file(dataframe_instance)
    if filemodel is None:
        return None
    # contenttype is an FK -> select_related (one JOIN);
    # dicts is a reverse FK -> prefetch_related (one extra query).
    links = list(
        dataframe_instance.links.select_related('contenttype').prefetch_related('dicts').all()
    )
    if not links:
        return None
    filename = filemodel.file.name.lower()
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(filemodel.file, skiprows=dataframe_instance.index_row)
        else:
            df = pd.read_excel(
                filemodel.file,
                sheet_name=dataframe_instance.sheet_name or 0,
                skiprows=dataframe_instance.index_row,
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