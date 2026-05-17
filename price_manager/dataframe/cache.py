"""Redis cache for reader-stage DataFrames.

Каждый upload-сессия и набор reader-аргументов имеют уникальный ключ.
Кэшируется только результат reader-а; трансформы исполняются над `.copy()`
кэшированного DataFrame на каждый запрос.

Бекенд кэша определяется в settings.CACHES — Redis (django_redis) в проде,
LocMemCache локально. `invalidate_session` использует django_redis-only
`cache.delete_pattern`, поэтому обёрнуто в try/except.
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle

import pandas as pd
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_PREFIX = 'dataframe:reader'
CACHE_TTL_SECONDS = 60 * 60  # 1h
MAX_PICKLE_BYTES = 50 * 1024 * 1024  # skip caching DataFrames over ~50MB


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
        return pickle.loads(raw)
    except Exception:
        logger.warning('dataframe.cache unpickle failed for key=%s', key, exc_info=True)
        return None


def set_cached_reader_df(key: str, df: pd.DataFrame) -> bool:
    """Store DataFrame in cache. Returns True on success, False on size guard or backend failure."""
    try:
        approx_size = int(df.memory_usage(deep=True).sum())
    except Exception:
        approx_size = 0
    if approx_size and approx_size > MAX_PICKLE_BYTES:
        logger.info('dataframe.cache skip set: df too large (%d bytes) key=%s', approx_size, key)
        return False
    try:
        blob = pickle.dumps(df, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        logger.warning('dataframe.cache pickle failed for key=%s', key, exc_info=True)
        return False
    if len(blob) > MAX_PICKLE_BYTES:
        logger.info('dataframe.cache skip set: pickle too large (%d bytes) key=%s', len(blob), key)
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
