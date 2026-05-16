"""Map a pandas DataFrame (output of the dataframe pipeline) to Product payloads.

The mapping describes which DataFrame column feeds which Product field, and which
columns feed CharacteristicType values. Category/Brand are looked up by name
(get_or_create). SKU is the upsert key.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Brand, Category, CharacteristicType, Product

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

        if not payload.get('sku'):
            errors['sku'] = 'SKU обязателен.'
        if not payload.get('name'):
            errors['name'] = 'Название обязательно.'

        results.append(RowResult(index=int(idx), payload=payload, errors=errors))
    return results


@transaction.atomic
def commit_rows(results: list[RowResult]) -> dict:
    """Persist valid rows. Category/Brand are get_or_create by name. SKU is upsert key."""
    created = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []

    for r in results:
        if not r.is_valid:
            skipped += 1
            errors.append({'index': r.index, 'errors': r.errors})
            continue

        payload = dict(r.payload)
        cat_name = payload.pop('category', None)
        brand_name = payload.pop('brand', None)
        sku = payload.pop('sku')

        defaults = {k: v for k, v in payload.items() if k in ('name', 'description', 'status', 'characteristics')}
        defaults.setdefault('status', Product.STATUS_DRAFT)

        if cat_name:
            cat, _ = Category.objects.get_or_create(parent=None, name=cat_name)
            defaults['category'] = cat
        if brand_name:
            brand, _ = Brand.objects.get_or_create(name=brand_name)
            defaults['brand'] = brand

        obj, was_created = Product.objects.update_or_create(sku=sku, defaults=defaults)
        if was_created:
            created += 1
        else:
            updated += 1

    return {'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors}
