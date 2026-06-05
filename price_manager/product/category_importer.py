"""Map a pandas DataFrame (output of the dataframe pipeline) to Category tree paths.

Each row supplies a path-string (e.g. "Электроника > Смартфоны > Android")
that is split into segments and resolved against the MPTT Category tree.

apply_mapping()  — pure in-memory pass; returns one CategoryRowResult per row.
commit_rows()    — persists only status='new' rows via Category.save() so MPTT
                   positions nodes automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .models import Category

STATUS_NEW = 'new'
STATUS_EXISTS = 'exists'
STATUS_INVALID = 'invalid'


@dataclass
class CategoryRowResult:
    index: int
    path: str
    segments: list[str]
    status: str  # 'new' | 'exists' | 'invalid'
    error: str = field(default='')

    def to_json(self) -> dict:
        out = {'index': self.index, 'path': self.path, 'segments': self.segments, 'status': self.status}
        if self.error:
            out['error'] = self.error
        return out


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


def _chain_exists(segments: list[str]) -> bool:
    """Return True if the complete chain (root→leaf) already exists in DB."""
    parent_id = None
    for name in segments:
        try:
            cat = Category.objects.get(parent_id=parent_id, name=name)
            parent_id = cat.pk
        except Category.DoesNotExist:
            return False
    return True


def apply_mapping(df: pd.DataFrame, mapping: dict) -> list[CategoryRowResult]:
    """Translate each DataFrame row into a CategoryRowResult.

    mapping keys:
      path_column — (required) column in df that contains the path string
      separator   — (optional, default '>') segment delimiter
    """
    path_column = (mapping or {}).get('path_column', '')
    separator = (mapping or {}).get('separator') or '>'

    results: list[CategoryRowResult] = []
    for idx, row in df.iterrows():
        raw = _cell(row, path_column) if path_column else None
        path_str = str(raw).strip() if raw is not None else ''

        if not path_str:
            results.append(CategoryRowResult(
                index=int(idx), path='', segments=[],
                status=STATUS_INVALID, error='Путь пустой или не найдена колонка.',
            ))
            continue

        segments = [s.strip() for s in path_str.split(separator)]
        if not segments or any(s == '' for s in segments):
            results.append(CategoryRowResult(
                index=int(idx), path=path_str, segments=segments,
                status=STATUS_INVALID, error='Путь содержит пустые сегменты.',
            ))
            continue

        exists = _chain_exists(segments)
        results.append(CategoryRowResult(
            index=int(idx), path=path_str, segments=segments,
            status=STATUS_EXISTS if exists else STATUS_NEW,
        ))

    return results


def commit_rows(results: list[CategoryRowResult]) -> dict:
    """Persist only status='new' rows; skip 'exists' and 'invalid'.

    Uses Category.save() per node so django-mptt positions the tree correctly.
    Returns {'created': N, 'skipped': N, 'invalid': N, 'errors': [...]}.
    """
    created = 0
    skipped = 0
    invalid = 0
    errors: list[dict] = []

    for r in results:
        if r.status == STATUS_INVALID:
            invalid += 1
            continue
        if r.status == STATUS_EXISTS:
            skipped += 1
            continue

        # status == 'new': walk chain, get_or_create each node
        try:
            parent = None
            for name in r.segments:
                cat, was_created = Category.objects.get_or_create(parent=parent, name=name)
                if was_created:
                    created += 1
                parent = cat
        except Exception as exc:
            errors.append({'index': r.index, 'path': r.path, 'error': str(exc)})

    return {'created': created, 'skipped': skipped, 'invalid': invalid, 'errors': errors}
