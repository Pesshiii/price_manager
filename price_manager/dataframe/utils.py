
import pandas as pd
from .models import FileModel, DictItem

def get_sheet_names(pk):
    '''
        Возвращает названия листов для датафрейма если он есть\\
        В противном случае Вызывает ошибку ObejectDoesNotExist
    '''

    filemodel = FileModel.objects.get(pk=pk)
    if not filemodel:
        raise BaseException(f'Файл не существует {pk}')
    if not filemodel.file:
        raise BaseException(f'Файл не найден: {pk}')
    sheet_names = pd.ExcelFile(filemodel.file, engine='calamine').sheet_names
    filemodel.file.close()
    return [(name, name) for name in sheet_names]


DICT_SHEMA={
    "type": "array",
    "title": "Shopping list",
    "description": "Add items to your shopping list",
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
    "maxItems": 20
}
def get_json_dicts(dictitems:list[DictItem])->list:
    return [
            {
                "key": dictitem.key,
                "value": dictitem.value
            }
            for dictitem in dictitems
        ]