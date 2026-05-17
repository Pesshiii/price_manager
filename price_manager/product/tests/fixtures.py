"""Helpers for product import e2e tests: CSV/XLSX builders, mapping/instructions, char-type factories."""
from __future__ import annotations

import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from product.models import CharacteristicType

DEFAULT_HEADER = ['sku', 'name', 'category', 'brand', 'color', 'weight']


def csv_upload(rows, name='data.csv', encoding='utf-8'):
    buf = io.StringIO()
    writer = csv.writer(buf)
    for r in rows:
        writer.writerow(r)
    return SimpleUploadedFile(name, buf.getvalue().encode(encoding), content_type='text/csv')


def xlsx_upload(rows, name='data.xlsx', sheet_name='Sheet1'):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for r in rows:
        ws.append([str(c) if c is not None else None for c in r])
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(
        name,
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


def bytes_upload(data: bytes, name='garbage.xlsx', content_type='application/octet-stream'):
    return SimpleUploadedFile(name, data, content_type=content_type)


def csv_instructions():
    return {'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []}


def xlsx_instructions():
    return {'reader': {'func': 'read_excel', 'args': {}}, 'transforms': []}


def default_mapping(extra_chars: dict | None = None):
    mapping = {
        'sku': {'column': 'sku'},
        'name': {'column': 'name'},
        'category': {'column': 'category'},
        'brand': {'column': 'brand'},
        'status': {'const': 'active'},
        'characteristics': {
            'color': {'column': 'color'},
            'weight': {'column': 'weight'},
        },
    }
    if extra_chars:
        mapping['characteristics'].update(extra_chars)
    return mapping


def make_char_type(name, value_type, *, label=None, options=None, required=False, categories=()):
    ct = CharacteristicType.objects.create(
        name=name,
        label=label or name,
        value_type=value_type,
        options=list(options) if options else [],
        required=required,
    )
    if categories:
        ct.categories.set(categories)
    return ct
