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
) -> tuple[pd.DataFrame, dict | None]:
    """Run the pipeline up to `up_to` transforms (inclusive of all if None).

    Returns ``(df, step_error)`` where ``step_error`` is ``None`` on full success
    or ``{"step_index": int, "message": str}`` when a Transform raises.  In the
    error case, ``df`` is the state **before** the failing step (i.e. after the
    last successful step).  The pipeline stops at the first error; subsequent
    steps are not attempted.

    Reader-stage errors (bad file format, unknown reader name) are NOT caught —
    they propagate as plain exceptions so callers can distinguish them from
    Transform errors.

    ``session_id`` is required as a keyword to make caching intent explicit at
    each call site. Pass ``None`` to opt out of caching (e.g. in unit tests that
    exercise the reader/transform plumbing directly without a real upload session).
    """
    instructions = df_obj.instructions or {}
    reader_cfg = instructions.get('reader') or {}

    # Reader errors propagate — no DataFrame to return in that case.
    df = _read_with_cache(reader_cfg, file, session_id)
    # Transforms mutate; the cached object must not be touched.
    df = df.copy()

    steps = instructions.get('transforms') or []
    if up_to is not None:
        steps = steps[:up_to]

    for i, step in enumerate(steps):
        try:
            spec = get_transform(step.get('func', ''))
            df = spec.func(df, **(step.get('args') or {}))
        except Exception as exc:  # noqa: BLE001
            return df, {'step_index': i, 'message': f'{type(exc).__name__}: {exc}'}

    return df, None


def apply(df_obj: Dataframe, file, *, session_id: str | None) -> pd.DataFrame:
    """Run the full pipeline.  Raises on any step error (including Reader errors).

    Callers that want graceful error handling with last-valid-state data should
    use ``apply_partial`` directly.
    """
    df, step_error = apply_partial(df_obj, file, up_to=None, session_id=session_id)
    if step_error is not None:
        raise RuntimeError(
            f"Pipeline step {step_error['step_index']} failed: {step_error['message']}"
        )
    return df
