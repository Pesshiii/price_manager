from __future__ import annotations

import io

import pandas as pd
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from .models import Dataframe
from .registry import READERS, TRANSFORMS, reader, transform
from .services import apply, apply_partial


def make_xlsx_bytes(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def make_csv_upload(rows, name='data.csv'):
    text = '\n'.join(','.join(str(c) for c in r) for r in rows).encode('utf-8')
    return SimpleUploadedFile(name, text, content_type='text/csv')


class RegistryTests(TestCase):
    def test_register_and_lookup(self):
        @reader('__test_reader', extensions=('xyz',))
        def _r(file):
            return pd.DataFrame()

        @transform('__test_transform')
        def _t(df):
            return df

        self.assertIn('__test_reader', READERS)
        self.assertIn('__test_transform', TRANSFORMS)
        # cleanup so we don't leak into other tests
        del READERS['__test_reader']
        del TRANSFORMS['__test_transform']


class ReaderTests(TestCase):
    def test_read_excel(self):
        buf = make_xlsx_bytes([['a', 'b'], ['1', '2'], ['3', '4']])
        upload = SimpleUploadedFile('x.xlsx', buf.getvalue())
        df_obj = Dataframe(
            name='t',
            instructions={'reader': {'func': 'read_excel', 'args': {}}, 'transforms': []},
        )
        df = apply(df_obj, upload)
        self.assertEqual(list(df.columns), ['a', 'b'])
        self.assertEqual(df.shape, (2, 2))

    def test_read_csv(self):
        upload = make_csv_upload([['a', 'b'], ['1', '2'], ['3', '4']])
        df_obj = Dataframe(
            name='t',
            instructions={'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []},
        )
        df = apply(df_obj, upload)
        self.assertEqual(list(df.columns), ['a', 'b'])
        self.assertEqual(df.shape, (2, 2))


class PipelineTests(TestCase):
    def _csv_obj(self, transforms):
        return Dataframe(
            name='t',
            instructions={'reader': {'func': 'read_csv', 'args': {}}, 'transforms': transforms},
        )

    def test_apply_pipeline_select_and_rename(self):
        upload = make_csv_upload([['a', 'b', 'c'], ['1', '2', '3'], ['4', '5', '6']])
        df_obj = self._csv_obj([
            {'func': 'select_columns', 'args': {'cols': 'a,b'}},
            {'func': 'rename_columns', 'args': {'mapping': 'a=alpha\nb=beta'}},
        ])
        df = apply(df_obj, upload)
        self.assertEqual(list(df.columns), ['alpha', 'beta'])
        self.assertEqual(df.shape, (2, 2))

    def test_apply_partial_stops_early(self):
        upload = make_csv_upload([['a', 'b', 'c'], ['1', '2', '3']])
        df_obj = self._csv_obj([
            {'func': 'select_columns', 'args': {'cols': 'a,b'}},
            {'func': 'rename_columns', 'args': {'mapping': 'a=alpha'}},
        ])
        df = apply_partial(df_obj, upload, up_to=1)
        self.assertEqual(list(df.columns), ['a', 'b'])


class ModelTests(TestCase):
    def test_clean_rejects_unknown_reader(self):
        df_obj = Dataframe(
            name='x',
            instructions={'reader': {'func': 'nope'}, 'transforms': []},
        )
        with self.assertRaises(ValidationError):
            df_obj.clean()

    def test_clean_rejects_unknown_transform(self):
        df_obj = Dataframe(
            name='x',
            instructions={
                'reader': {'func': 'read_csv', 'args': {}},
                'transforms': [{'func': 'nope', 'args': {}}],
            },
        )
        with self.assertRaises(ValidationError):
            df_obj.clean()


