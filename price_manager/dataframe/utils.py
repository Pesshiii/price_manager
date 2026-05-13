
import pandas as pd
from .models import FileModel, DictItem


def get_sheet_names(pk):
    """Return list of (name, name) tuples for sheets in the file with the given FileModel pk."""
    filemodel = FileModel.objects.get(pk=pk)
    filename = filemodel.file.name.lower()
    if filename.endswith('.csv'):
        return [('Sheet1', 'Sheet1')]
    try:
        excel = pd.ExcelFile(filemodel.file, engine='calamine')
        return [(name, name) for name in excel.sheet_names]
    except Exception:
        return [('', 'Выберите лист')]
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