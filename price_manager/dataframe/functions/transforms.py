from __future__ import annotations

import pandas as pd

from ..registry import ArgSpec, transform


def _as_list(v):
    if v is None or v == '':
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split(',') if s.strip()]


def _as_mapping(v) -> dict[str, str]:
    if isinstance(v, dict):
        return {str(k): str(val) for k, val in v.items()}
    if not v:
        return {}
    out: dict[str, str] = {}
    for line in str(v).splitlines():
        if '=' in line:
            k, val = line.split('=', 1)
            out[k.strip()] = val.strip()
    return out


@transform(
    'select_columns',
    label='Оставить колонки',
    args=(ArgSpec(name='cols', type='columns', label='Колонки', required=True),),
)
def select_columns(df: pd.DataFrame, cols) -> pd.DataFrame:
    cols = _as_list(cols)
    keep = [c for c in cols if c in df.columns]
    return df[keep].copy()


@transform(
    'rename_columns',
    label='Переименовать колонки',
    args=(ArgSpec(name='mapping', type='column_mapping',
                  label='Старое имя → новое', required=True),),
)
def rename_columns(df: pd.DataFrame, mapping) -> pd.DataFrame:
    return df.rename(columns=_as_mapping(mapping)).copy()


@transform(
    'drop_na',
    label='Удалить пустые строки',
    args=(ArgSpec(name='subset', type='columns', label='По колонкам (пусто = все)'),),
)
def drop_na(df: pd.DataFrame, subset='') -> pd.DataFrame:
    cols = _as_list(subset)
    subset_arg = [c for c in cols if c in df.columns] or None
    return df.dropna(subset=subset_arg).copy()


@transform(
    'replace_values',
    label='Заменить значения в колонке',
    args=(
        ArgSpec(name='column', type='column', label='Колонка', required=True),
        ArgSpec(name='mapping', type='value_mapping',
                label='Старое значение → новое', required=True),
    ),
)
def replace_values(df: pd.DataFrame, column, mapping) -> pd.DataFrame:
    df = df.copy()
    if column in df.columns:
        df[column] = df[column].replace(_as_mapping(mapping))
    return df


@transform(
    'to_numeric',
    label='Привести к числу',
    args=(
        ArgSpec(name='columns', type='columns', label='Колонки', required=True),
        ArgSpec(name='errors', type='str', label='Ошибки', default='coerce',
                choices=['raise', 'coerce', 'ignore']),
    ),
)
def to_numeric(df: pd.DataFrame, columns, errors='coerce') -> pd.DataFrame:
    df = df.copy()
    for c in _as_list(columns):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors=errors or 'coerce')
    return df
