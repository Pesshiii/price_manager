
import pandas as pd
from .models import FileModel

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
    return sheet_names