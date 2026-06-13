"""Preview and commit helpers for safe ``CharacteristicType`` mutations.

Two flavours of mutation need a migration of every product's JSONB
``characteristics``:

* **retype** — changing ``value_type`` may invalidate stored values. We use a
  throwaway in-memory copy of the type to call ``CharacteristicType.validate_value``
  against the *new* type so the coercion rules stay in lockstep with normal
  product writes (single source of truth — see ``models.py``).
* **rename** — changing the slug means rewriting the dict key in every row.
  Different from retype, the only failure case is a key collision (the new
  name is already present in some products).

Preview functions are synchronous and read-only.  Commit functions
(``commit_retype``, ``commit_rename``) are called from Celery tasks in
``product/tasks.py`` via a thin wrapper — pass a ``progress_callback`` to
receive ``rows_done`` counts after each batch.
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Any, Callable

from django.core.exceptions import ValidationError

from ..models import CharacteristicMutationJob, CharacteristicType, Product

# Read directly from the environment so this module stays independent of
# importer.py.  Same env var — same operational knob, different import path.
MUTATION_COMMIT_BATCH_SIZE = int(os.environ.get('IMPORT_COMMIT_BATCH_SIZE', '500'))


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


# ----- shared iteration helpers -------------------------------------------


def _iter_products_with_key(name: str):
    return (
        Product.objects
        .filter(characteristics__has_key=name)
        .only('id', 'characteristics')
        .iterator(chunk_size=max(MUTATION_COMMIT_BATCH_SIZE, 500))
    )


def _flush_batch(batch: list[Product]) -> None:
    if not batch:
        return
    Product.objects.bulk_update(batch, ['characteristics'])
    batch.clear()


# ----- commit helpers ------------------------------------------------------


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


def commit_retype(job, *, progress_callback: Callable[[int], None] | None = None) -> dict:
    """Migrate every product's JSONB value for the job's characteristic to a new value_type.

    Sets job.rows_total before iteration so the SPA can switch from indeterminate
    to a progress bar.  Calls progress_callback(rows_done) after each batch.
    Updates CharacteristicType.value_type on success.
    """
    ct = job.char_type
    payload = job.payload or {}
    new_value_type = payload['new_value_type']
    probe = _make_probe(ct, new_value_type)

    rows_total = Product.objects.filter(characteristics__has_key=ct.name).count()
    CharacteristicMutationJob.objects.filter(pk=job.pk).update(rows_total=rows_total, rows_done=0)

    counters = {'updated': 0, 'mapped': 0, 'defaulted': 0, 'nulled': 0, 'dropped': 0}
    batch: list[Product] = []
    processed = 0

    for product in _iter_products_with_key(ct.name):
        chars = dict(product.characteristics or {})
        raw = chars.get(ct.name)
        action, new_value = coerce_with_strategy(probe, raw, payload)
        if action == 'dropped':
            chars.pop(ct.name, None)
            counters['dropped'] += 1
        elif action == 'nulled':
            chars[ct.name] = None
            counters['nulled'] += 1
        elif action == 'defaulted':
            if new_value is None:
                chars.pop(ct.name, None)
            else:
                chars[ct.name] = new_value
            counters['defaulted'] += 1
        elif action == 'mapped':
            chars[ct.name] = new_value
            counters['mapped'] += 1
        else:  # 'keep' — already coerced cleanly
            if new_value is None:
                chars.pop(ct.name, None)
            else:
                chars[ct.name] = new_value
        counters['updated'] += 1
        product.characteristics = chars
        processed += 1
        batch.append(product)
        if len(batch) >= MUTATION_COMMIT_BATCH_SIZE:
            _flush_batch(batch)
            if progress_callback:
                progress_callback(processed)

    _flush_batch(batch)
    if progress_callback:
        progress_callback(processed)

    ct.value_type = new_value_type
    ct.save(update_fields=['value_type'])

    return counters


def commit_rename(job, *, progress_callback: Callable[[int], None] | None = None) -> dict:
    """Rename a CharacteristicType slug, migrating the JSONB key in every product.

    Sets job.rows_total before iteration.  Calls progress_callback(rows_done) after
    each batch (including batches whose only progress was skipped rows).
    Updates CharacteristicType.name on success.
    """
    ct = job.char_type
    payload = job.payload or {}
    old_name = ct.name
    new_name = payload['new_name']
    on_conflict = payload.get('on_conflict', ONCONFLICT_OVERWRITE)
    if new_name == old_name:
        raise ValueError('new_name must differ from current name')

    rows_total = Product.objects.filter(characteristics__has_key=old_name).count()
    CharacteristicMutationJob.objects.filter(pk=job.pk).update(rows_total=rows_total, rows_done=0)

    counters = {'renamed': 0, 'collisions': 0, 'skipped': 0}
    batch: list[Product] = []
    processed = 0

    for product in _iter_products_with_key(old_name):
        chars = dict(product.characteristics or {})
        processed += 1  # count every iterated product, including skipped
        if new_name in chars:
            counters['collisions'] += 1
            if on_conflict == ONCONFLICT_SKIP_ROW:
                counters['skipped'] += 1
                # Skipped rows don't enter the batch, so emit progress explicitly
                # every batch_size iterations to keep the bar moving.
                if processed % MUTATION_COMMIT_BATCH_SIZE == 0 and progress_callback:
                    progress_callback(processed)
                continue
            if on_conflict == ONCONFLICT_KEEP_EXISTING:
                chars.pop(old_name, None)
            else:  # overwrite
                chars[new_name] = chars.pop(old_name)
        else:
            chars[new_name] = chars.pop(old_name)
        counters['renamed'] += 1
        product.characteristics = chars
        batch.append(product)
        if len(batch) >= MUTATION_COMMIT_BATCH_SIZE:
            _flush_batch(batch)
            if progress_callback:
                progress_callback(processed)

    _flush_batch(batch)
    if progress_callback:
        progress_callback(processed)

    ct.name = new_name
    ct.save(update_fields=['name'])

    return counters
