from __future__ import annotations

import io

import pandas as pd
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
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


class RegistryTests(SimpleTestCase):
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


class ReaderTests(SimpleTestCase):
    def test_read_excel(self):
        buf = make_xlsx_bytes([['a', 'b'], ['1', '2'], ['3', '4']])
        upload = SimpleUploadedFile('x.xlsx', buf.getvalue())
        df_obj = Dataframe(
            name='t',
            instructions={'reader': {'func': 'read_excel', 'args': {}}, 'transforms': []},
        )
        df = apply(df_obj, upload, session_id=None)
        self.assertEqual(list(df.columns), ['a', 'b'])
        self.assertEqual(df.shape, (2, 2))

    def test_read_csv(self):
        upload = make_csv_upload([['a', 'b'], ['1', '2'], ['3', '4']])
        df_obj = Dataframe(
            name='t',
            instructions={'reader': {'func': 'read_csv', 'args': {}}, 'transforms': []},
        )
        df = apply(df_obj, upload, session_id=None)
        self.assertEqual(list(df.columns), ['a', 'b'])
        self.assertEqual(df.shape, (2, 2))


class PipelineTests(SimpleTestCase):
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
        df = apply(df_obj, upload, session_id=None)
        self.assertEqual(list(df.columns), ['alpha', 'beta'])
        self.assertEqual(df.shape, (2, 2))

    def test_apply_partial_stops_early(self):
        upload = make_csv_upload([['a', 'b', 'c'], ['1', '2', '3']])
        df_obj = self._csv_obj([
            {'func': 'select_columns', 'args': {'cols': 'a,b'}},
            {'func': 'rename_columns', 'args': {'mapping': 'a=alpha'}},
        ])
        df, step_error = apply_partial(df_obj, upload, up_to=1, session_id=None)
        self.assertEqual(list(df.columns), ['a', 'b'])
        self.assertIsNone(step_error)

    def test_apply_partial_success_returns_none_error(self):
        """When all steps complete without error, step_error is None."""
        upload = make_csv_upload([['a', 'b'], ['1', '2'], ['3', '4']])
        df_obj = self._csv_obj([
            {'func': 'select_columns', 'args': {'cols': 'a'}},
            {'func': 'rename_columns', 'args': {'mapping': 'a=sku'}},
        ])
        df, step_error = apply_partial(df_obj, upload, session_id=None)
        self.assertIsNone(step_error)
        self.assertEqual(list(df.columns), ['sku'])

    def test_apply_partial_error_at_step_0(self):
        """When step 0 raises, apply_partial returns (reader_output, step_error with index 0).
        The DataFrame is the raw reader output — transforms have not run."""
        upload = make_csv_upload([['a', 'b'], ['1', '2']])
        df_obj = self._csv_obj([
            {'func': 'select_columns', 'args': {'cols': 'NONEXISTENT_COLS_THAT_RAISE'}},
        ])
        # select_columns with an entirely missing column list returns an empty df,
        # which is valid. We need a transform that actually raises.
        # Use an unknown transform func name to force KeyError in get_transform().
        df_obj_bad = self._csv_obj([
            {'func': 'DOES_NOT_EXIST', 'args': {}},
        ])
        df, step_error = apply_partial(df_obj_bad, upload, session_id=None)
        self.assertIsNotNone(step_error)
        self.assertEqual(step_error['step_index'], 0)
        self.assertIn('DOES_NOT_EXIST', step_error['message'])
        # df should be the reader output (2 rows, columns a and b)
        self.assertEqual(list(df.columns), ['a', 'b'])

    def test_apply_partial_error_at_step_2_of_4(self):
        """When step 2 raises, data is the state after step 1; step_error.step_index == 2."""
        upload = make_csv_upload([['a', 'b', 'c'], ['1', '2', '3']])
        df_obj = self._csv_obj([
            {'func': 'select_columns', 'args': {'cols': 'a,b'}},        # step 0: ok
            {'func': 'rename_columns', 'args': {'mapping': 'a=alpha'}},  # step 1: ok
            {'func': 'DOES_NOT_EXIST', 'args': {}},                      # step 2: raises
            {'func': 'rename_columns', 'args': {'mapping': 'b=beta'}},  # step 3: never runs
        ])
        df, step_error = apply_partial(df_obj, upload, session_id=None)
        self.assertIsNotNone(step_error)
        self.assertEqual(step_error['step_index'], 2)
        # Data is the state after step 1: columns are ['alpha', 'b']
        self.assertEqual(list(df.columns), ['alpha', 'b'])

    def test_apply_raises_on_step_error(self):
        """apply() re-raises when a transform step fails — contract for Celery tasks."""
        upload = make_csv_upload([['a'], ['1']])
        df_obj = self._csv_obj([{'func': 'DOES_NOT_EXIST', 'args': {}}])
        with self.assertRaises(Exception):
            apply(df_obj, upload, session_id=None)


class CacheTests(SimpleTestCase):
    """Tests for the reader cache (cache.py).

    All tests go through the public interface only: set_cached_reader_df /
    get_cached_reader_df.  Internal serialisation format is not verified.
    """

    def _make_df(self):
        return pd.DataFrame({'sku': ['A1', 'B2'], 'price': [10.0, 20.0]})

    def test_round_trip(self):
        """Storing a DataFrame and retrieving it by the same key returns
        an identical DataFrame (same columns, same values)."""
        from .cache import get_cached_reader_df, reader_cache_key, set_cached_reader_df
        key = reader_cache_key('test-session-rt', {'func': 'read_csv'})
        df = self._make_df()
        stored = set_cached_reader_df(key, df)
        self.assertTrue(stored)
        retrieved = get_cached_reader_df(key)
        self.assertIsNotNone(retrieved)
        pd.testing.assert_frame_equal(df, retrieved)

    def test_size_guard_rejects_oversized_df(self):
        """A DataFrame whose serialised size exceeds MAX_CACHE_BYTES is NOT
        cached; set_cached_reader_df returns False without raising."""
        from unittest.mock import patch

        import dataframe.cache as cache_mod
        from .cache import reader_cache_key, set_cached_reader_df
        key = reader_cache_key('test-session-size', {'func': 'read_csv'})
        df = self._make_df()
        # Patch the limit to 1 byte so any DataFrame is "too large".
        with patch.object(cache_mod, 'MAX_CACHE_BYTES', 1):
            result = set_cached_reader_df(key, df)
        self.assertFalse(result)

    def test_set_backend_failure_returns_false(self):
        """If the cache backend raises during set, set_cached_reader_df
        returns False and does NOT propagate the exception."""
        from unittest.mock import patch

        from django.core.cache import cache

        from .cache import reader_cache_key, set_cached_reader_df
        key = reader_cache_key('test-session-setfail', {'func': 'read_csv'})
        df = self._make_df()
        with patch.object(cache, 'set', side_effect=Exception('redis down')):
            result = set_cached_reader_df(key, df)
        self.assertFalse(result)

    def test_get_backend_failure_returns_none(self):
        """If the cache backend raises during get, get_cached_reader_df
        returns None and does NOT propagate the exception."""
        from unittest.mock import patch

        from django.core.cache import cache

        from .cache import get_cached_reader_df, reader_cache_key
        key = reader_cache_key('test-session-getfail', {'func': 'read_csv'})
        with patch.object(cache, 'get', side_effect=Exception('redis down')):
            result = get_cached_reader_df(key)
        self.assertIsNone(result)


class ModelTests(SimpleTestCase):
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


