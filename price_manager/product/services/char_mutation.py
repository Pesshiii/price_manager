"""Preview / commit helpers for safe ``CharacteristicType`` mutations.

Two flavours of mutation need a migration of every product's JSONB
``characteristics``:

* **retype** — changing ``value_type`` may invalidate stored values. We use a
  throwaway in-memory copy of the type to call ``CharacteristicType.validate_value``
  against the *new* type so the coercion rules stay in lockstep with normal
  product writes (single source of truth — see ``models.py``).
* **rename** — changing the slug means rewriting the dict key in every row.
  Different from retype, the only failure case is a key collision (the new
  name is already present in some products).

Preview functions are synchronous (read-only); the actual write happens in
Celery (`product/tasks.py:run_char_retype` / `run_char_rename`).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from django.core.exceptions import ValidationError

from ..models import CharacteristicType, Product


# How many distinct invalid raw values we report from preview. Anything past
# this is dropped from the response (with ``truncated=true``) so the payload
# stays small even when the catalog has tens of thousands of garbage values.
UNIQUE_INVALID_LIMIT = 200

# Threshold the SPA uses to switch UIs (per-value table vs. single fallback).
# Exported so tests / docs can reference one constant.
SMALL_INVALID_THRESHOLD = 10


def _make_probe(ct: CharacteristicType, new_value_type: str) -> CharacteristicType:
    """Return an unsaved CharacteristicType configured with the candidate type.

    We reuse ``validate_value`` for coercion — same code path as Product writes.
    Options are preserved so 'choice' validation still works.
    """
    probe = CharacteristicType(
        name=ct.name,
        label=ct.label,
        value_type=new_value_type,
        options=list(ct.options or []),
        unit=ct.unit,
        required=False,  # required-ness doesn't matter for coercion; '' is treated as None
    )
    return probe


def _raw_repr(value: Any) -> str:
    """Stable string key for grouping invalid raw values in preview output.

    JSON has no concept of int/str mix in a dict key, and we want the UI to
    show users the value the way it's stored. Bools become 'true'/'false';
    everything else uses str().
    """
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def preview_retype(ct: CharacteristicType, new_value_type: str) -> dict:
    """Scan every product carrying ``ct.name`` and report values that won't
    coerce to ``new_value_type``.

    Response shape::

        {
          'total_with_key': int,   # products that have ct.name in their JSONB
          'invalid_count': int,    # products whose current value won't coerce
          'unique_invalid': [{'value': str, 'count': int}, ...],
          'truncated': bool,
        }
    """
    if new_value_type not in dict(CharacteristicType.VALUE_TYPE_CHOICES):
        raise ValueError(f'Unknown value_type: {new_value_type}')

    probe = _make_probe(ct, new_value_type)
    invalid: Counter = Counter()
    total_with_key = 0
    invalid_count = 0

    qs = (
        Product.objects
        .filter(characteristics__has_key=ct.name)
        .only('id', 'characteristics')
    )
    for row in qs.iterator(chunk_size=1000):
        total_with_key += 1
        raw = row.characteristics.get(ct.name)
        if raw is None or raw == '':
            continue  # None/empty becomes None on coerce; never an error here
        try:
            probe.validate_value(raw)
        except ValidationError:
            invalid_count += 1
            invalid[_raw_repr(raw)] += 1

    most = invalid.most_common(UNIQUE_INVALID_LIMIT)
    return {
        'total_with_key': total_with_key,
        'invalid_count': invalid_count,
        'unique_invalid': [{'value': v, 'count': c} for v, c in most],
        'truncated': len(invalid) > UNIQUE_INVALID_LIMIT,
    }


def preview_rename(ct: CharacteristicType, new_name: str) -> dict:
    """Scan for collisions if ``ct.name`` were renamed to ``new_name``.

    A collision is a product that already has BOTH keys — we'd have to choose
    one. Pure rename (only old key present) is reported via the
    ``total_to_rename`` counter.

    Response shape::

        {
          'total_to_rename': int,
          'collision_count': int,
          'collisions': [{'product_id': int, 'sku': str}, ...],  # capped at 100
        }
    """
    if not new_name:
        raise ValueError('new_name is required')
    if new_name == ct.name:
        raise ValueError('new_name must differ from current name')

    total_to_rename = 0
    collisions = []
    collision_count = 0

    qs = (
        Product.objects
        .filter(characteristics__has_key=ct.name)
        .only('id', 'sku', 'characteristics')
    )
    for row in qs.iterator(chunk_size=1000):
        total_to_rename += 1
        if new_name in (row.characteristics or {}):
            collision_count += 1
            if len(collisions) < 100:
                collisions.append({'product_id': row.id, 'sku': row.sku})

    return {
        'total_to_rename': total_to_rename,
        'collision_count': collision_count,
        'collisions': collisions,
    }


# ----- commit helpers (called from Celery tasks) ---------------------------


FALLBACK_DROP = 'drop'
FALLBACK_NULL = 'null'
FALLBACK_DEFAULT = 'default'
RETYPE_FALLBACKS = (FALLBACK_DROP, FALLBACK_NULL, FALLBACK_DEFAULT)

ONCONFLICT_OVERWRITE = 'overwrite'
ONCONFLICT_KEEP_EXISTING = 'keep_existing'
ONCONFLICT_SKIP_ROW = 'skip_row'
RENAME_CONFLICT_STRATEGIES = (
    ONCONFLICT_OVERWRITE,
    ONCONFLICT_KEEP_EXISTING,
    ONCONFLICT_SKIP_ROW,
)


def coerce_with_strategy(
    probe: CharacteristicType,
    raw: Any,
    payload: dict,
) -> tuple[str, Any]:
    """Apply value_map → fallback chain. Returns ``(action, new_value)``.

    ``action`` is one of:
      - ``'keep'``  — coerced cleanly; ``new_value`` is the coerced result.
      - ``'mapped'`` — replaced via ``payload['value_map']``; coerced from replacement.
      - ``'defaulted'`` — replaced by ``payload['default_value']``.
      - ``'nulled'`` — set to ``None``.
      - ``'dropped'`` — caller should pop the key.
    """
    if raw is None or raw == '':
        return 'keep', None
    try:
        return 'keep', probe.validate_value(raw)
    except ValidationError:
        pass

    value_map = payload.get('value_map') or {}
    key = _raw_repr(raw)
    if key in value_map:
        replacement = value_map[key]
        # Replacements still go through validate_value to catch bad UI input.
        return 'mapped', probe.validate_value(replacement)

    fallback = payload.get('fallback', FALLBACK_DROP)
    if fallback == FALLBACK_DEFAULT:
        default_value = payload.get('default_value')
        return 'defaulted', probe.validate_value(default_value)
    if fallback == FALLBACK_NULL:
        return 'nulled', None
    return 'dropped', None
