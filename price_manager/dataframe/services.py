from __future__ import annotations

import pandas as pd

from .models import Dataframe
from .registry import get_reader, get_transform


def _normalize_file(file):
    if hasattr(file, 'seek'):
        try:
            file.seek(0)
        except Exception:
            pass
    return file


def apply_partial(df_obj: Dataframe, file, up_to: int | None = None) -> pd.DataFrame:
    instructions = df_obj.instructions or {}
    reader_cfg = instructions.get('reader') or {}
    reader_spec = get_reader(reader_cfg.get('func', ''))
    file = _normalize_file(file)
    df = reader_spec.func(file, **(reader_cfg.get('args') or {}))

    if isinstance(df, dict):
        df = next(iter(df.values()))

    steps = instructions.get('transforms') or []
    if up_to is not None:
        steps = steps[:up_to]
    for step in steps:
        spec = get_transform(step.get('func', ''))
        df = spec.func(df, **(step.get('args') or {}))
    return df


def apply(df_obj: Dataframe, file) -> pd.DataFrame:
    return apply_partial(df_obj, file, up_to=None)
