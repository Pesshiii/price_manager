from __future__ import annotations

import pandas as pd

from .cache import (
    get_cached_reader_df,
    reader_cache_key,
    set_cached_reader_df,
)
from .models import Dataframe
from .registry import get_reader, get_transform


def _normalize_file(file):
    if hasattr(file, 'seek'):
        try:
            file.seek(0)
        except Exception:
            pass
    return file


def _read_with_cache(reader_cfg: dict, file, session_id: str | None) -> pd.DataFrame:
    """Return reader output, hitting Redis cache when `session_id` is provided."""
    if session_id:
        key = reader_cache_key(session_id, reader_cfg)
        cached = get_cached_reader_df(key)
        if cached is not None:
            return cached

    reader_spec = get_reader(reader_cfg.get('func', ''))
    file = _normalize_file(file)
    df = reader_spec.func(file, **(reader_cfg.get('args') or {}))
    if isinstance(df, dict):
        df = next(iter(df.values()))

    if session_id:
        set_cached_reader_df(reader_cache_key(session_id, reader_cfg), df)
    return df


def apply_partial(
    df_obj: Dataframe,
    file,
    up_to: int | None = None,
    *,
    session_id: str | None,
) -> pd.DataFrame:
    """Run the pipeline up to `up_to` transforms (inclusive of all if None).

    `session_id` is required as a keyword to make caching intent explicit at each
    call site. Pass `None` to opt out of caching (e.g. in unit tests that exercise
    the reader/transform plumbing directly without a real upload session).
    """
    instructions = df_obj.instructions or {}
    reader_cfg = instructions.get('reader') or {}

    df = _read_with_cache(reader_cfg, file, session_id)
    # Transforms mutate; the cached object must not be touched.
    df = df.copy()

    steps = instructions.get('transforms') or []
    if up_to is not None:
        steps = steps[:up_to]
    for step in steps:
        spec = get_transform(step.get('func', ''))
        df = spec.func(df, **(step.get('args') or {}))
    return df


def apply(df_obj: Dataframe, file, *, session_id: str | None) -> pd.DataFrame:
    return apply_partial(df_obj, file, up_to=None, session_id=session_id)
