
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

    filemodel = FileModel.objects.get(pk=pk)
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

    filemodel = FileModel.objects.get(pk=file_pk)
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
        result = [('', '---------')] + [(col, col) for col in df.columns]
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        return [('', '---------')]
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