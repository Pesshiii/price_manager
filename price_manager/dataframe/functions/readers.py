from __future__ import annotations

import pandas as pd

from ..registry import ArgSpec, reader


@reader(
    'read_excel',
    extensions=('xls', 'xlsx', 'xlsm'),
    label='Excel',
    args=(
        ArgSpec(name='sheet_name', type='str', label='Лист',
                help_text='Имя или индекс листа. Пусто = первый лист.'),
        ArgSpec(name='header', type='int', label='Строка заголовка', default=0),
        ArgSpec(name='skiprows', type='int', label='Пропустить строк', default=0),
    ),
)
def read_excel(file, sheet_name='', header=0, skiprows=0):
    sheet: object
    if sheet_name in ('', None):
        sheet = 0
    else:
        try:
            sheet = int(sheet_name)
        except (TypeError, ValueError):
            sheet = sheet_name
    file.seek(0)
    try:
        df = pd.read_excel(
            file,
            engine='calamine',
            sheet_name=sheet,
            header=int(header) if header not in ('', None) else 0,
            skiprows=int(skiprows) if skiprows not in ('', None) else 0,
            dtype=str,
        )
    except Exception:
        file.seek(0)
        df = pd.read_excel(
            file,
            sheet_name=sheet,
            header=int(header) if header not in ('', None) else 0,
            skiprows=int(skiprows) if skiprows not in ('', None) else 0,
            dtype=str,
        )
    return df


@reader(
    'read_csv',
    extensions=('csv', 'tsv', 'txt'),
    label='CSV',
    args=(
        ArgSpec(name='sep', type='str', label='Разделитель', default=','),
        ArgSpec(name='encoding', type='str', label='Кодировка', default='utf-8'),
        ArgSpec(name='header', type='int', label='Строка заголовка', default=0),
        ArgSpec(name='skiprows', type='int', label='Пропустить строк', default=0),
    ),
)
def read_csv(file, sep=',', encoding='utf-8', header=0, skiprows=0):
    file.seek(0)
    return pd.read_csv(
        file,
        sep=sep or ',',
        encoding=encoding or 'utf-8',
        header=int(header) if header not in ('', None) else 0,
        skiprows=int(skiprows) if skiprows not in ('', None) else 0,
        dtype=str,
    )
