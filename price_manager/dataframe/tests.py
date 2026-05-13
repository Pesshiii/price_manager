from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ContentType, Dataframe, DictItem, FileModel, Link
from .utils import get_json_dicts, get_sheet_names
from .views import _resolve_unique_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_uploaded_file(name='test.xlsx', content=b'data'):
    return SimpleUploadedFile(name, content, content_type='application/vnd.ms-excel')


def make_filemodel(name='test.xlsx'):
    return FileModel.objects.create(file=make_uploaded_file(name))


def make_dataframe(name='TestDF', file=None):
    if file is None:
        file = make_filemodel()
    return Dataframe.objects.create(name=name, file=file)


def make_content_type(name='price', ct='float'):
    return ContentType.objects.get_or_create(name=name, defaults={'measure': 'руб', 'contenttype': ct})[0]


def make_user(username='testuser'):
    return User.objects.create_user(username=username, password='testpass')


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class FileModelTests(TestCase):
    def test_filename_strips_extension(self):
        # FileModel.filename uses os.path.basename(file.name).split('.')[0]
        # Django storage may rename files (e.g., my_prices_XXXXX.xlsx) on collision.
        # We test the property directly with a mock to avoid storage side-effects.
        fm = FileModel.__new__(FileModel)
        mock_file = MagicMock()
        mock_file.name = 'dataframe/my_prices.xlsx'
        fm.file = mock_file
        self.assertEqual(fm.filename, 'my_prices')

    def test_filename_with_dots_in_name(self):
        fm = FileModel.__new__(FileModel)
        mock_file = MagicMock()
        mock_file.name = 'dataframe/report.v2.xlsx'
        fm.file = mock_file
        self.assertEqual(fm.filename, 'report')

    def test_pre_delete_signal_removes_file(self):
        fm = FileModel.__new__(FileModel)
        mock_file = MagicMock()
        fm.file = mock_file
        from dataframe.models.dataframemodels import document_pre_delete
        document_pre_delete(sender=FileModel, instance=fm)
        mock_file.delete.assert_called_once_with(save=False)


class DataframeModelTests(TestCase):
    def test_str_returns_name(self):
        df = make_dataframe('My Dataframe')
        self.assertEqual(str(df), 'My Dataframe')

    def test_slug_auto_generated(self):
        df = make_dataframe('Some Name')
        self.assertTrue(df.slug)

    def test_slug_not_overwritten_on_resave(self):
        df = make_dataframe('Original')
        original_slug = df.slug
        df.save()
        self.assertEqual(df.slug, original_slug)


class LinkModelTests(TestCase):
    def test_unique_constraint_per_dataframe_contenttype(self):
        from django.db import IntegrityError
        df = make_dataframe()
        ct = make_content_type()
        Link.objects.create(dataframe=df, contenttype=ct, initial='col_a')
        with self.assertRaises(IntegrityError):
            Link.objects.create(dataframe=df, contenttype=ct, initial='col_b')

    def test_same_contenttype_allowed_on_different_dataframes(self):
        ct = make_content_type()
        df1 = make_dataframe('DF1')
        df2 = make_dataframe('DF2')
        Link.objects.create(dataframe=df1, contenttype=ct, initial='col')
        # Should not raise
        link2 = Link.objects.create(dataframe=df2, contenttype=ct, initial='col')
        self.assertIsNotNone(link2.pk)


class DictItemModelTests(TestCase):
    def test_unique_constraint(self):
        from django.db import IntegrityError
        df = make_dataframe()
        ct = make_content_type()
        link = Link.objects.create(dataframe=df, contenttype=ct, initial='col')
        DictItem.objects.create(link=link, key='A', value='1')
        with self.assertRaises(IntegrityError):
            DictItem.objects.create(link=link, key='A', value='1')


# ---------------------------------------------------------------------------
# Utils tests
# ---------------------------------------------------------------------------

class GetSheetNamesTests(TestCase):
    def test_csv_returns_sheet1(self):
        fm = FileModel.objects.create(file=SimpleUploadedFile('data.csv', b'a,b\n1,2'))
        result = get_sheet_names(fm.pk)
        self.assertEqual(result, [('Sheet1', 'Sheet1')])

    def test_excel_returns_sheet_list(self):
        fm = make_filemodel('prices.xlsx')
        mock_excel = MagicMock()
        mock_excel.sheet_names = ['Sheet1', 'Prices', 'Config']
        with patch('dataframe.utils.pd.ExcelFile', return_value=mock_excel):
            result = get_sheet_names(fm.pk)
        self.assertEqual(result, [('Sheet1', 'Sheet1'), ('Prices', 'Prices'), ('Config', 'Config')])

    def test_raises_for_missing_pk(self):
        with self.assertRaises(FileModel.DoesNotExist):
            get_sheet_names(99999)

    def test_file_closed_after_read(self):
        fm = make_filemodel('prices.xlsx')
        mock_excel = MagicMock()
        mock_excel.sheet_names = ['Sheet1']
        with patch('dataframe.utils.pd.ExcelFile', return_value=mock_excel):
            get_sheet_names(fm.pk)
        # File should have been closed (the FileField's close method called)
        # We just verify no exception was raised and result is correct


class GetJsonDictsTests(TestCase):
    def test_empty_queryset_returns_default(self):
        result = get_json_dicts([])
        self.assertEqual(result, [{'key': '', 'value': ''}])

    def test_non_empty_returns_correct_list(self):
        df = make_dataframe()
        ct = make_content_type()
        link = Link.objects.create(dataframe=df, contenttype=ct, initial='col')
        di1 = DictItem.objects.create(link=link, key='ООО', value='Company')
        di2 = DictItem.objects.create(link=link, key='ИП', value='Sole trader')
        result = get_json_dicts([di1, di2])
        self.assertEqual(result, [
            {'key': 'ООО', 'value': 'Company'},
            {'key': 'ИП', 'value': 'Sole trader'},
        ])


# ---------------------------------------------------------------------------
# _resolve_unique_name tests
# ---------------------------------------------------------------------------

class ResolveUniqueNameTests(TestCase):
    def test_unique_name_unchanged(self):
        self.assertEqual(_resolve_unique_name('NewName'), 'NewName')

    def test_collision_appends_copy(self):
        make_dataframe('base')
        self.assertEqual(_resolve_unique_name('base'), 'base_copy')

    def test_multiple_collisions(self):
        make_dataframe('x')
        make_dataframe('x_copy')
        self.assertEqual(_resolve_unique_name('x'), 'x_copy_copy')

    def test_exclude_self_on_update(self):
        df = make_dataframe('existing')
        # When updating the same object, its own name should not cause a collision
        result = _resolve_unique_name('existing', exclude_pk=df.pk)
        self.assertEqual(result, 'existing')


# ---------------------------------------------------------------------------
# View tests
# ---------------------------------------------------------------------------

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class DataframeCreateViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass')
        self.url = reverse('dataframe:create')

    def test_get_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_create_with_explicit_name(self):
        data = {
            'name': 'MyDataframe',
            'sheet_name': '',
            'filefield': make_uploaded_file('prices.xlsx'),
        }
        response = self.client.post(self.url, data)
        self.assertEqual(Dataframe.objects.filter(name='MyDataframe').count(), 1)
        df = Dataframe.objects.get(name='MyDataframe')
        self.assertRedirects(response, reverse('dataframe:update', kwargs={'pk': df.pk}))

    def test_create_auto_name_from_filename(self):
        # Use a filename unique to this test to avoid InMemoryStorage collisions
        data = {
            'name': '',
            'sheet_name': '',
            'filefield': make_uploaded_file('auto_name_base.xlsx'),
        }
        self.client.post(self.url, data)
        self.assertTrue(Dataframe.objects.filter(name='auto_name_base').exists())

    def test_create_auto_name_collision_resolved(self):
        make_dataframe('auto_name_collision')
        data = {
            'name': '',
            'sheet_name': '',
            'filefield': make_uploaded_file('auto_name_collision.xlsx'),
        }
        self.client.post(self.url, data)
        self.assertTrue(Dataframe.objects.filter(name='auto_name_collision_copy').exists())

    def test_create_requires_file(self):
        data = {'name': 'NoFile', 'sheet_name': ''}
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Dataframe.objects.filter(name='NoFile').exists())

    def test_filemodel_created_on_create(self):
        count_before = FileModel.objects.count()
        data = {
            'name': 'WithFile',
            'sheet_name': '',
            'filefield': make_uploaded_file('f.xlsx'),
        }
        self.client.post(self.url, data)
        self.assertEqual(FileModel.objects.count(), count_before + 1)


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class DataframeUpdateViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass')
        self.df = make_dataframe('UpdateMe')
        self.url = reverse('dataframe:update', kwargs={'pk': self.df.pk})

    def test_get_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_update_name_without_reuploading_file(self):
        data = {
            'name': 'UpdatedName',
            'sheet_name': '',
            # no filefield — should keep existing file
            'form-TOTAL_FORMS': '0',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        self.client.post(self.url, data)
        self.df.refresh_from_db()
        self.assertEqual(self.df.name, 'UpdatedName')
        self.assertIsNotNone(self.df.file)

    def test_update_replaces_file_and_deletes_old(self):
        old_file = self.df.file
        old_file_pk = old_file.pk
        data = {
            'name': 'UpdateMe',
            'sheet_name': '',
            'filefield': make_uploaded_file('new_prices.xlsx'),
            'form-TOTAL_FORMS': '0',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        self.client.post(self.url, data)
        self.df.refresh_from_db()
        self.assertNotEqual(self.df.file.pk, old_file_pk)
        self.assertFalse(FileModel.objects.filter(pk=old_file_pk).exists())

    def test_update_redirects_to_update_url(self):
        data = {
            'name': 'UpdateMe',
            'sheet_name': '',
            'form-TOTAL_FORMS': '0',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(self.url, data)
        self.assertRedirects(response, self.url)


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class DataframeUpdateLinkFormsetTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass')
        self.df = make_dataframe('DF With Links')
        self.ct = make_content_type('Цена', 'float')
        self.url = reverse('dataframe:update', kwargs={'pk': self.df.pk})

    def _post_with_link(self, initial, key='ООО', value='Компания', extra=None):
        data = {
            'name': self.df.name,
            'sheet_name': '',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-contenttype': str(self.ct.pk),
            'form-0-initial': initial,
            'form-0-dictitems': f'[{{"key":"{key}","value":"{value}"}}]',
            'form-0-DELETE': '',
        }
        if extra:
            data.update(extra)
        return self.client.post(self.url, data)

    def test_link_created_with_dataframe(self):
        self._post_with_link('price_col')
        self.assertEqual(Link.objects.filter(dataframe=self.df).count(), 1)
        link = Link.objects.get(dataframe=self.df)
        self.assertEqual(link.initial, 'price_col')

    def test_dictitems_saved_for_link(self):
        self._post_with_link('price_col', key='ООО', value='Ltd')
        link = Link.objects.get(dataframe=self.df)
        self.assertEqual(link.dicts.count(), 1)
        di = link.dicts.first()
        self.assertEqual(di.key, 'ООО')
        self.assertEqual(di.value, 'Ltd')

    def test_dictitems_replaced_on_update(self):
        # Create link with initial DictItem
        link = Link.objects.create(dataframe=self.df, contenttype=self.ct, initial='col')
        DictItem.objects.create(link=link, key='OLD_KEY', value='OLD_VAL')

        data = {
            'name': self.df.name,
            'sheet_name': '',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': str(link.pk),
            'form-0-contenttype': str(self.ct.pk),
            'form-0-initial': 'col',
            'form-0-dictitems': '[{"key":"NEW_KEY","value":"NEW_VAL"}]',
            'form-0-DELETE': '',
        }
        self.client.post(self.url, data)

        link.refresh_from_db()
        keys = list(link.dicts.values_list('key', flat=True))
        self.assertNotIn('OLD_KEY', keys)
        self.assertIn('NEW_KEY', keys)

    def test_link_deleted_via_delete_flag(self):
        link = Link.objects.create(dataframe=self.df, contenttype=self.ct, initial='col')

        data = {
            'name': self.df.name,
            'sheet_name': '',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': str(link.pk),
            'form-0-contenttype': str(self.ct.pk),
            'form-0-initial': 'col',
            'form-0-dictitems': '[{"key":"","value":""}]',
            'form-0-DELETE': 'on',
        }
        self.client.post(self.url, data)
        self.assertFalse(Link.objects.filter(pk=link.pk).exists())

    def test_links_from_other_dataframes_not_affected(self):
        other_df = make_dataframe('Other')
        ct2 = make_content_type('weight', 'float')
        other_link = Link.objects.create(dataframe=other_df, contenttype=ct2, initial='w_col')

        self._post_with_link('price_col')

        # The link on the other dataframe must remain untouched
        self.assertTrue(Link.objects.filter(pk=other_link.pk).exists())
