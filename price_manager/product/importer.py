"""Map a pandas DataFrame (output of the dataframe pipeline) to Product payloads.

The mapping describes which DataFrame column feeds which Product field, and which
columns feed CharacteristicType values. Category/Brand are looked up by name
(get_or_create). SKU is the upsert key.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from .models import Brand, Category, CharacteristicType, Product

# Batch size for chunked commit. Each batch is its own transaction so a
# huge import does not blow up the Postgres rollback log nor pin the entire
# RowResult list in worker memory at once. Override via env for tuning.
IMPORT_COMMIT_BATCH_SIZE = int(os.environ.get('IMPORT_COMMIT_BATCH_SIZE', '500'))

SCALAR_FIELDS = ('sku', 'name', 'description', 'status')
FK_FIELDS = ('category', 'brand')


@dataclass
class RowResult:
    index: int
    payload: dict
    errors: dict = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_json(self) -> dict:
        return {'index': self.index, 'payload': self.payload, 'errors': self.errors}


def _cell(row: pd.Series, column: str) -> Any:
    if column not in row:
        return None
    value = row[column]
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        value = value.strip()
        if value == '':
            return None
    return value


def _resolve_source(row: pd.Series, spec: dict) -> Any:
    if not isinstance(spec, dict):
        return None
    if 'const' in spec:
        return spec['const']
    column = spec.get('column')
    if column:
        return _cell(row, column)
    return None


def apply_mapping(df: pd.DataFrame, mapping: dict) -> list[RowResult]:
    """Translate each DataFrame row into a Product payload + per-row validation errors.

    The result is purely in-memory; commit_rows() persists valid rows.
    """
    char_types_by_name = {
        ct.name: ct
        for ct in CharacteristicType.objects.filter(
            name__in=list((mapping.get('characteristics') or {}).keys())
        )
    }

    results: list[RowResult] = []
    for idx, row in df.iterrows():
        payload: dict[str, Any] = {'characteristics': {}}
        errors: dict[str, str] = {}

        for field_name in SCALAR_FIELDS:
            spec = (mapping or {}).get(field_name)
            if not spec:
                continue
            value = _resolve_source(row, spec)
            if value is not None:
                payload[field_name] = str(value) if field_name != 'description' else str(value)

        for field_name in FK_FIELDS:
            spec = (mapping or {}).get(field_name)
            if not spec:
                continue
            value = _resolve_source(row, spec)
            if value in (None, ''):
                continue
            payload[field_name] = str(value).strip()

        chars_mapping = (mapping or {}).get('characteristics') or {}
        for char_name, spec in chars_mapping.items():
            raw = _resolve_source(row, spec)
            if raw is None:
                continue
            ct = char_types_by_name.get(char_name)
            if ct is None:
                errors[f'characteristics.{char_name}'] = f"Тип характеристики '{char_name}' не найден."
                continue
            try:
                coerced = ct.validate_value(raw)
            except ValidationError as exc:
                errors[f'characteristics.{char_name}'] = exc.messages[0] if exc.messages else str(exc)
                continue
            if coerced is not None:
                payload['characteristics'][char_name] = coerced

        # Dynamic (EAV) characteristics: name/value/[unit] sourced from columns,
        # one entry per dynamic spec. Validated lazily in commit_rows because
        # the target CharacteristicType may not exist yet (auto-created there).
        dynamic_specs = (mapping or {}).get('dynamic_characteristics') or []
        dynamic_entries: list[dict] = []
        for spec in dynamic_specs:
            if not isinstance(spec, dict):
                continue
            name_col = spec.get('name_column')
            value_col = spec.get('value_column')
            unit_col = spec.get('unit_column')
            if not name_col or not value_col:
                continue
            raw_name = _cell(row, name_col)
            raw_value = _cell(row, value_col)
            if raw_name in (None, '') or raw_value in (None, ''):
                continue
            entry: dict[str, Any] = {'name': str(raw_name).strip(), 'value': raw_value}
            if unit_col:
                u = _cell(row, unit_col)
                if u not in (None, ''):
                    entry['unit'] = str(u).strip()
            dynamic_entries.append(entry)
        if dynamic_entries:
            payload['_dynamic_characteristics'] = dynamic_entries

        if not payload.get('sku'):
            errors['sku'] = 'SKU обязателен.'
        if not payload.get('name'):
            errors['name'] = 'Название обязательно.'

        results.append(RowResult(index=int(idx), payload=payload, errors=errors))
    return results


def _resolve_dynamic_types(
    results: list[RowResult],
) -> dict[str, CharacteristicType]:
    """Pre-pass over results: auto-create CharacteristicType for every unique
    slug seen in `_dynamic_characteristics`. First-seen unit wins when the
    type already exists with an empty unit. Returns slug -> instance.
    """
    # slug -> (raw_name, first_unit_seen or None)
    seen: dict[str, tuple[str, str | None]] = {}
    for r in results:
        if not r.is_valid:
            continue
        for entry in r.payload.get('_dynamic_characteristics', []) or []:
            raw_name = entry.get('name')
            if not raw_name:
                continue
            slug = slugify(raw_name, allow_unicode=True)[:64]
            if not slug:
                continue
            if slug in seen:
                continue
            seen[slug] = (raw_name, entry.get('unit') or None)

    if not seen:
        return {}

    existing = {
        ct.name: ct
        for ct in CharacteristicType.objects.filter(name__in=list(seen.keys()))
    }

    for slug, (raw_name, first_unit) in seen.items():
        # Truncate to the model's max_length values — supplier files routinely
        # ship long free-form text in the "unit" column (e.g. multi-word
        # descriptions), which would otherwise blow up with
        # `DataError: value too long for type character varying(32)`.
        label_value = (raw_name or '')[:255]
        unit_value = (first_unit or '')[:32]
        ct = existing.get(slug)
        if ct is None:
            ct = CharacteristicType.objects.create(
                name=slug,
                label=label_value,
                value_type=CharacteristicType.VALUE_STRING,
                unit=unit_value,
            )
            existing[slug] = ct
        elif first_unit and not ct.unit:
            CharacteristicType.objects.filter(pk=ct.pk).update(unit=unit_value)
            ct.unit = unit_value

    return existing


def _commit_batch(
    batch: list[RowResult],
    char_types_by_name: dict[str, CharacteristicType],
    linked_pairs: set[tuple[int, int]],
) -> tuple[int, int, int, list[dict]]:
    """Persist a single batch inside one transaction. Returns per-batch counters."""
    created = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []

    with transaction.atomic():
        for r in batch:
            if not r.is_valid:
                skipped += 1
                errors.append({'index': r.index, 'errors': r.errors})
                continue

            payload = dict(r.payload)
            cat_name = payload.pop('category', None)
            brand_name = payload.pop('brand', None)
            sku = payload.pop('sku')
            dynamic_entries = payload.pop('_dynamic_characteristics', []) or []

            # Merge dynamic chars into the standard `characteristics` dict.
            # Static mapping wins on slug collision (left there by apply_mapping).
            if dynamic_entries:
                chars = dict(payload.get('characteristics') or {})
                for entry in dynamic_entries:
                    raw_name = entry.get('name') or ''
                    slug = slugify(raw_name, allow_unicode=True)[:64]
                    if not slug or slug in chars:
                        continue
                    if slug not in char_types_by_name:
                        # Skip — type creation happens in _resolve_dynamic_types
                        # before commit_rows; missing here means slug was empty.
                        continue
                    chars[slug] = str(entry.get('value'))
                payload['characteristics'] = chars

            defaults = {
                k: v for k, v in payload.items()
                if k in ('name', 'description', 'status', 'characteristics')
            }
            defaults.setdefault('status', Product.STATUS_DRAFT)

            cat = None
            if cat_name:
                cat, _ = Category.objects.get_or_create(parent=None, name=cat_name)
                defaults['category'] = cat
            if brand_name:
                brand, _ = Brand.objects.get_or_create(name=brand_name)
                defaults['brand'] = brand

            _, was_created = Product.objects.update_or_create(sku=sku, defaults=defaults)
            if was_created:
                created += 1
            else:
                updated += 1

            if cat is not None:
                chars = defaults.get('characteristics') or {}
                for key, value in chars.items():
                    if value in (None, ''):
                        continue
                    ct = char_types_by_name.get(key)
                    if ct is None:
                        continue
                    pair = (ct.id, cat.id)
                    if pair in linked_pairs:
                        continue
                    ct.categories.add(cat)
                    linked_pairs.add(pair)

    return created, updated, skipped, errors


def commit_rows(results: list[RowResult]) -> dict:
    """Persist valid rows. Category/Brand are get_or_create by name. SKU is upsert key.

    Iterates ``results`` in chunks of ``IMPORT_COMMIT_BATCH_SIZE``, each chunk
    inside its own ``transaction.atomic``. This keeps the rollback log bounded
    on large imports and lets the GC reclaim already-written ``RowResult``
    objects between batches.

    When a row has both a category and non-empty characteristic values, the
    CharacteristicType <-> Category M2M is auto-extended so the type appears
    under that category afterwards.
    """
    created = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []

    char_keys: set[str] = set()
    for r in results:
        if r.is_valid:
            char_keys.update((r.payload.get('characteristics') or {}).keys())
    char_types_by_name = {
        ct.name: ct
        for ct in CharacteristicType.objects.filter(name__in=char_keys)
    } if char_keys else {}

    # Auto-create CharacteristicType for every unique dynamic-char slug, then
    # merge those types into the lookup so the M2M auto-link path also sees them.
    dynamic_types = _resolve_dynamic_types(results)
    char_types_by_name.update(dynamic_types)

    linked_pairs: set[tuple[int, int]] = set()
    batch_size = max(1, IMPORT_COMMIT_BATCH_SIZE)

    for start in range(0, len(results), batch_size):
        batch = results[start:start + batch_size]
        c, u, s, errs = _commit_batch(batch, char_types_by_name, linked_pairs)
        created += c
        updated += u
        skipped += s
        errors.extend(errs)

    return {'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors}
