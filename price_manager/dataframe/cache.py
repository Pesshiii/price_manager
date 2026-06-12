"""Redis cache for reader-stage DataFrames.

Каждый upload-сессия и набор reader-аргументов имеют уникальный ключ.
Кэшируется только результат reader-а; трансформы исполняются над `.copy()`
кэшированного DataFrame на каждый запрос.

Сериализация: Apache Arrow / Feather (zstd-сжатие).  Feather даёт 5–10×
сжатие относительно pickle, что позволяет кэшировать XLSX-каталоги размером
50–500 MB в памяти.  Размер проверяется по сжатому blob-у (MAX_CACHE_BYTES).

Бекенд кэша определяется в settings.CACHES — Redis (django_redis) в проде,
LocMemCache локально. `invalidate_session` использует django_redis-only
`cache.delete_pattern`, поэтому обёрнуто в try/except.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging

import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_PREFIX = 'dataframe:reader'
CACHE_TTL_SECONDS = 60 * 60  # 1h
MAX_CACHE_BYTES = 200 * 1024 * 1024  # skip caching blobs over ~200MB (compressed)


def reader_cache_key(session_id: str, reader_cfg: dict) -> str:
    blob = json.dumps(reader_cfg or {}, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha1(blob.encode('utf-8')).hexdigest()[:16]
    return f'{CACHE_PREFIX}:{session_id}:{digest}'


def get_cached_reader_df(key: str) -> pd.DataFrame | None:
    try:
        raw = cache.get(key)
    except Exception:
        logger.warning('dataframe.cache get failed for key=%s', key, exc_info=True)
        return None
    if not raw:
        return None
    try:
        return feather.read_feather(io.BytesIO(raw))
    except Exception:
        logger.warning('dataframe.cache deserialise failed for key=%s', key, exc_info=True)
        return None


def set_cached_reader_df(key: str, df: pd.DataFrame) -> bool:
    """Store DataFrame in cache. Returns True on success, False on size guard or backend failure."""
    buf = io.BytesIO()
    try:
        feather.write_feather(df, buf, compression='zstd')
    except Exception:
        logger.warning('dataframe.cache serialise failed for key=%s', key, exc_info=True)
        return False

    blob = buf.getvalue()
    if len(blob) > MAX_CACHE_BYTES:
        logger.info(
            'dataframe.cache skip set: blob too large (%d bytes) key=%s', len(blob), key
        )
        return False

    try:
        cache.set(key, blob, CACHE_TTL_SECONDS)
        return True
    except Exception:
        logger.warning('dataframe.cache set failed for key=%s', key, exc_info=True)
        return False


def invalidate_session(session_id: str) -> None:
    """Drop all reader-cache entries for the given session_id. No-op on non-Redis backends."""
    pattern = f'{CACHE_PREFIX}:{session_id}:*'
    delete_pattern = getattr(cache, 'delete_pattern', None)
    if callable(delete_pattern):
        try:
            delete_pattern(pattern)
        except Exception:
            logger.warning('dataframe.cache delete_pattern failed for session=%s', session_id, exc_info=True)
