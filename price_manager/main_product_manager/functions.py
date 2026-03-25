from django.core.cache import cache
from .tables import AVAILABLE_COLUMN_MAP, DEFAULT_VISIBLE_COLUMNS

CACHE_TTL = 60 * 60 * 24 * 30  # 30 дней

def _cache_key(user_id: int) -> str:
    return f"mainprice:selected_columns:user:{user_id}"

def normalize_columns(columns):
    valid = [col for col in columns if col in AVAILABLE_COLUMN_MAP]
    return valid or DEFAULT_VISIBLE_COLUMNS

def save_user_columns(user, columns):
    if not user.is_authenticated:
        return
    cache.set(_cache_key(user.id), normalize_columns(columns), CACHE_TTL)

def load_user_columns(user):
    if not user.is_authenticated:
        return DEFAULT_VISIBLE_COLUMNS
    return cache.get(_cache_key(user.id), DEFAULT_VISIBLE_COLUMNS)