from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from pim_api import SiteAPI

from core.models import TaskRunHistory
from product import tasks
from product.models import Product, ProductPhoto
from product.services import photos
from product.services.photos import product_photos, refresh_product_photos

LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
HOST = 'pim.example.kz'


def link(sharing_id):
    return f'{HOST}/sharings/{sharing_id}.jpg'


def public(sharing_id):
    return f'https://{link(sharing_id)}'


class FakePim:
    """Списки PIM в памяти — с отбором where, сортировкой по id и maxSize.

    Понимает ровно то, что шлёт services/photos: id greaterThan (страницы),
    fileId in, createdAt greaterThanOrEquals.
    """

    def __init__(self, product_files=(), sharings=(), fail_on_call=None):
        self.tables = {'ProductFile': list(product_files), 'Sharing': list(sharings)}
        self.calls = []
        self.fail_on_call = fail_on_call

    def get(self, method, timeout=None):
        self.calls.append(method)
        if self.fail_on_call == len(self.calls):
            raise RuntimeError('PIM недоступен')
        rows = sorted(self.tables[method.name], key=lambda row: row['id'])
        for where in method.where or []:
            rows = [row for row in rows if self._matches(row, where)]
        return {'total': len(rows), 'list': rows[:method.maxSize]}

    @staticmethod
    def _matches(row, where):
        value = row.get(where.attribute)
        if where.type == 'greaterThan':
            return value > where.value
        if where.type == 'greaterThanOrEquals':
            return value >= where.value
        if where.type == 'in':
            return value in where.value
        raise AssertionError(f'неожиданный отбор {where.type}')

    def sharing_calls(self):
        return [call for call in self.calls if call.name == 'Sharing']


def product_file(row_id, product_id, file_id, name='photo.jpg', main=False, sorting=0):
    return {'id': row_id, 'productId': product_id, 'fileId': file_id, 'fileName': name,
            'isMainImage': main, 'sorting': sorting}


def sharing(row_id, file_id, created='2026-10-01 10:00:00', **fields):
    return {'id': row_id, 'fileId': file_id, 'link': link(row_id), 'active': True, 'available': True,
            'validTill': None, 'createdAt': created, **fields}


@override_settings(PIM_HOST=HOST)
class RefreshProductPhotosTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(number='SKU-1', raw_data={'id': 'p-1'})

    def run_refresh(self, pim, **kwargs):
        with patch.object(SiteAPI, 'get', side_effect=pim.get):
            return refresh_product_photos(**kwargs)

    def mirrored(self, product=None):
        return list(ProductPhoto.objects.filter(product=product or self.product)
                    .values_list('pim_file_id', 'position', 'is_main', 'public_url'))

    def test_mirrors_image_files_in_display_order_with_their_public_links(self):
        pim = FakePim(
            product_files=[
                product_file('pf-1', 'p-1', 'f-b', name='b.jpg', sorting=5),
                product_file('pf-2', 'p-1', 'f-main', name='z.webp', main=True, sorting=9),
                product_file('pf-3', 'p-1', 'f-a', name='a.png', sorting=5),
                product_file('pf-4', 'p-1', 'f-pdf', name='Инструкция.pdf'),
                product_file('pf-5', 'p-other', 'f-x', name='x.jpg'),
            ],
            sharings=[sharing('s-1', 'f-main'), sharing('s-2', 'f-x')],
        )

        self.run_refresh(pim, full=True)

        self.assertEqual(self.mirrored(), [
            ('f-main', 0, True, public('s-1')),
            ('f-a', 1, False, ''),
            ('f-b', 2, False, ''),
        ])
        self.assertEqual(ProductPhoto.objects.count(), 3)

    def test_every_local_product_on_one_pim_product_gets_the_photos(self):
        twin = Product.objects.create(number='SKU-1-TWIN', raw_data={'id': 'p-1'})
        pim = FakePim(product_files=[product_file('pf-1', 'p-1', 'f-1')])

        self.run_refresh(pim, full=True)

        self.assertEqual([row[0] for row in self.mirrored()], ['f-1'])
        self.assertEqual([row[0] for row in self.mirrored(twin)], ['f-1'])

    def test_rescan_drops_unlinked_files_adds_new_and_reorders(self):
        ProductPhoto.objects.create(product=self.product, pim_file_id='f-gone', position=0, is_main=True)
        ProductPhoto.objects.create(product=self.product, pim_file_id='f-stays', position=1,
                                    public_url=public('s-old'))
        pim = FakePim(product_files=[
            product_file('pf-1', 'p-1', 'f-new', main=True),
            product_file('pf-2', 'p-1', 'f-stays', sorting=1),
        ])

        self.run_refresh(pim, full=False, since=timezone.now())

        self.assertEqual(self.mirrored(), [
            ('f-new', 0, True, ''),
            ('f-stays', 1, False, public('s-old')),
        ])

    def test_a_product_whose_files_are_gone_loses_its_photos(self):
        ProductPhoto.objects.create(product=self.product, pim_file_id='f-1')
        stale = Product.objects.create(number='SKU-2', raw_data={})
        ProductPhoto.objects.create(product=stale, pim_file_id='f-2')

        self.run_refresh(FakePim(), full=True)

        self.assertFalse(ProductPhoto.objects.exists())

    def test_unusable_links_are_ignored(self):
        past = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        pim = FakePim(
            product_files=[product_file(f'pf-{n}', 'p-1', f'f-{n}', sorting=n) for n in range(5)],
            sharings=[
                sharing('s-0', 'f-0', active=False),
                sharing('s-1', 'f-1', available=False),
                sharing('s-2', 'f-2', validTill=past),
                {**sharing('s-3', 'f-3'), 'link': 'evil.example.com/sharings/s-3.jpg'},
                sharing('s-4', 'f-4'),
            ],
        )

        self.run_refresh(pim, full=True)

        self.assertEqual([row[3] for row in self.mirrored()], ['', '', '', '', public('s-4')])

    def test_incremental_run_adds_new_links_and_looks_up_new_files_but_clears_nothing(self):
        ProductPhoto.objects.create(product=self.product, pim_file_id='f-known', position=0,
                                    public_url=public('s-revoked'))
        ProductPhoto.objects.create(product=self.product, pim_file_id='f-waiting', position=1)
        pim = FakePim(
            product_files=[
                product_file('pf-1', 'p-1', 'f-known', sorting=0),
                product_file('pf-2', 'p-1', 'f-waiting', sorting=1),
                product_file('pf-3', 'p-1', 'f-new', sorting=2),
            ],
            sharings=[
                sharing('s-recent', 'f-waiting', created='2026-10-11 23:00:00'),
                sharing('s-old', 'f-new', created='2026-09-01 10:00:00'),
            ],
        )

        self.run_refresh(pim, since=datetime(2026, 10, 12, 5, 30, tzinfo=dt_timezone.utc))

        self.assertEqual([row[3] for row in self.mirrored()], [public('s-revoked'), public('s-recent'), public('s-old')])
        self.assertTrue(all(call.where for call in pim.sharing_calls()),
                        'инкрементальный проход не должен читать Sharing целиком')

    def test_full_run_clears_revoked_links(self):
        ProductPhoto.objects.create(product=self.product, pim_file_id='f-1', public_url=public('s-revoked'))
        pim = FakePim(product_files=[product_file('pf-1', 'p-1', 'f-1')])

        self.run_refresh(pim, full=True)

        self.assertEqual(self.mirrored(), [('f-1', 0, False, '')])

    def test_first_run_without_a_previous_success_is_full(self):
        pim = FakePim(product_files=[product_file('pf-1', 'p-1', 'f-1')],
                      sharings=[sharing('s-1', 'f-1', created='2020-01-01 00:00:00')])

        stats = self.run_refresh(pim, since=None)

        self.assertTrue(stats['full'])
        self.assertEqual(self.mirrored(), [('f-1', 0, False, public('s-1'))])

    def test_pages_go_by_id_so_every_row_arrives(self):
        pim = FakePim(product_files=[product_file(f'pf-{n}', 'p-1', f'f-{n}', sorting=n) for n in range(5)])

        with patch.object(photos, 'PAGE_SIZE', 2):
            self.run_refresh(pim, full=True)

        self.assertEqual(len(self.mirrored()), 5)
        file_calls = [call for call in pim.calls if call.name == 'ProductFile']
        self.assertEqual(len(file_calls), 3)
        self.assertEqual([where.value for where in file_calls[1].where], ['pf-1'])
        self.assertEqual(file_calls[1].where[0].type, 'greaterThan')

    def test_a_pim_failure_mid_scan_writes_nothing(self):
        ProductPhoto.objects.create(product=self.product, pim_file_id='f-1')
        pim = FakePim(product_files=[product_file(f'pf-{n}', 'p-1', f'f-{n}') for n in range(5)],
                      fail_on_call=2)

        with patch.object(photos, 'PAGE_SIZE', 2), self.assertRaises(RuntimeError):
            self.run_refresh(pim, full=True)

        self.assertEqual([row[0] for row in self.mirrored()], ['f-1'])

    def test_a_failed_link_lookup_for_new_files_writes_nothing_either(self):
        # Иначе строки остались бы без ссылок до воскресенья: на следующую ночь
        # они уже не новые, а их ссылки старше водяного знака.
        pim = FakePim(product_files=[product_file('pf-1', 'p-1', 'f-new')],
                      sharings=[sharing('s-old', 'f-new', created='2026-09-01 10:00:00')],
                      fail_on_call=3)  # ProductFile, Sharing по createdAt, Sharing по fileId

        with self.assertRaises(RuntimeError):
            self.run_refresh(pim, since=datetime(2026, 10, 12, 5, 30, tzinfo=dt_timezone.utc))

        self.assertFalse(ProductPhoto.objects.exists())
        self.assertEqual(pim.calls[-1].where[0].attribute, 'fileId')

    def test_a_product_deleted_during_the_scan_is_skipped(self):
        pim = FakePim(product_files=[product_file('pf-1', 'p-1', 'f-1')])
        products = photos._local_products()
        Product.objects.filter(pk=self.product.pk).delete()

        with patch.object(photos, '_local_products', return_value=products):
            stats = self.run_refresh(pim, full=True)

        self.assertEqual(stats['created'], 0)
        self.assertFalse(ProductPhoto.objects.exists())


class ProductPhotosTests(TestCase):
    def test_unsynced_photos_fall_back_to_the_main_image_through_the_proxy(self):
        photos_ = product_photos(Product(raw_data={'mainImageId': 'img-1'}))

        self.assertEqual(photos_, [{'src': '/products/pim-image/img-1/medium/', 'fallback': '',
                                    'zoom': '/products/pim-image/img-1/large/', 'zoom_fallback': ''}])

    def test_mirrored_photos_in_order_with_proxy_as_fallback_of_a_public_link(self):
        product = Product.objects.create(number='SKU-1', raw_data={'mainImageId': 'ignored'})
        ProductPhoto.objects.create(product=product, pim_file_id='f-2', position=1)
        ProductPhoto.objects.create(product=product, pim_file_id='f-1', position=0, public_url=public('s-1'))

        photos_ = product_photos(product)

        self.assertEqual([photo['src'] for photo in photos_], [public('s-1'), '/products/pim-image/f-2/medium/'])
        self.assertEqual(photos_[0]['fallback'], '/products/pim-image/f-1/medium/')
        self.assertEqual(photos_[0]['zoom_fallback'], '/products/pim-image/f-1/large/')

    def test_no_photos(self):
        self.assertEqual(product_photos(Product(raw_data={})), [])


@override_settings(CACHES=LOCMEM_CACHE)
class RefreshProductPhotosTaskTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_links_are_taken_since_the_last_successful_run(self):
        started = timezone.now() - timedelta(days=1)
        TaskRunHistory.objects.create(task_name=photos.TASK_NAME, status='success', started_at=started,
                                      finished_at=started, duration_ms=1)
        TaskRunHistory.objects.create(task_name=photos.TASK_NAME, status='error', started_at=timezone.now(),
                                      finished_at=timezone.now(), duration_ms=1)
        stats = {'created': 2, 'updated': 1, 'deleted': 0, 'links': 3}

        with patch.object(tasks, 'refresh_product_photos', return_value=stats) as refresh:
            payload = tasks.refresh_product_photos_task()

        refresh.assert_called_once_with(full=False, since=started)
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['updated_count'], 6)

    def test_full_flag_is_passed_through(self):
        stats = {'created': 0, 'updated': 0, 'deleted': 0, 'links': 0}

        with patch.object(tasks, 'refresh_product_photos', return_value=stats) as refresh:
            tasks.refresh_product_photos_task(full=True)

        self.assertTrue(refresh.call_args.kwargs['full'])
