"""Фото из PIM через прокси.

PIM отдаёт и миниатюры, и оригиналы только с Authorization-Token — анонимный
запрос, то есть <img src> в браузере, получает 401. Поэтому браузер ходит к
нам, а мы — в PIM с токеном. Сеть здесь не трогается: site и httpx подменены.
"""
from unittest.mock import Mock, patch

import httpx
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from product.models import Product

from .utils import fetch_pim_image, pim_image_url

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'pim-image-tests'}}
FILE_RECORD = {'mediumThumbnailUrl': 'pim.test/thumbnail/medium/f-1.png',
               'downloadUrl': 'pim.test/images/f-1.jpg'}


def image_response(status=200, content_type='image/png', body=b'\x89PNG...'):
    return Mock(status_code=status, headers={'content-type': content_type}, content=body,
                is_redirect=False)


def redirect_response(location):
    return Mock(status_code=302, headers={'content-type': 'text/html', 'location': location},
                content=b'', is_redirect=True)


@override_settings(CACHES=LOCMEM, PIM_HOST='pim.test', PIM_TOKEN='secret-token')
class FetchPimImageTests(TestCase):
    def setUp(self):
        cache.clear()

    def _fetch(self, record=FILE_RECORD, response=None, file_id='f-1', size='medium'):
        with patch('main_product_manager.utils.site') as site, \
                patch('main_product_manager.utils.httpx.get') as get:
            site.get.return_value = record
            get.return_value = response or image_response()
            result = fetch_pim_image(file_id, size)
        return result, get

    def test_fetches_with_the_token_from_the_pim_host(self):
        result, get = self._fetch()

        self.assertEqual(result, (b'\x89PNG...', 'image/png'))
        url = get.call_args.args[0] if get.call_args.args else get.call_args.kwargs['url']
        self.assertEqual(url, 'https://pim.test/thumbnail/medium/f-1.png')
        self.assertEqual(get.call_args.kwargs['headers'], {'Authorization-Token': 'secret-token'})
        self.assertFalse(get.call_args.kwargs['follow_redirects'])

    def test_the_token_never_goes_to_another_host(self):
        """Адрес картинки приходит из ответа PIM. Указал он на чужой хост —
        отправить туда токен значило бы его раздать."""
        result, get = self._fetch(record={'mediumThumbnailUrl': 'cdn.elsewhere.test/f-1.png'})

        self.assertIsNone(result)
        get.assert_not_called()

    def test_same_host_redirect_is_followed_with_the_token(self):
        """Живой PIM отвечает на миниатюру 302 на относительный /upload/… ."""
        with patch('main_product_manager.utils.site') as site, \
                patch('main_product_manager.utils.httpx.get') as get:
            site.get.return_value = FILE_RECORD
            get.side_effect = [redirect_response('/upload/thumbnails/f-1.png'), image_response()]
            result = fetch_pim_image('f-1')

        self.assertEqual(result[1], 'image/png')
        second = get.call_args_list[1]
        self.assertEqual(second.args[0], 'https://pim.test/upload/thumbnails/f-1.png')
        self.assertEqual(second.kwargs['headers'], {'Authorization-Token': 'secret-token'})

    def test_redirect_to_another_host_is_not_followed(self):
        with patch('main_product_manager.utils.site') as site, \
                patch('main_product_manager.utils.httpx.get') as get:
            site.get.return_value = FILE_RECORD
            get.side_effect = [redirect_response('https://cdn.elsewhere.test/f-1.png'),
                               image_response()]
            result = fetch_pim_image('f-1')

        self.assertIsNone(result)
        self.assertEqual(get.call_count, 1)

    def test_a_redirect_loop_gives_up(self):
        with patch('main_product_manager.utils.site') as site, \
                patch('main_product_manager.utils.httpx.get') as get:
            site.get.return_value = FILE_RECORD
            get.return_value = redirect_response('/upload/again.png')
            result = fetch_pim_image('f-1')

        self.assertIsNone(result)
        self.assertEqual(get.call_count, 4)

    def test_second_request_is_served_from_the_cache(self):
        self._fetch()
        result, get = self._fetch()

        self.assertEqual(result[1], 'image/png')
        get.assert_not_called()

    def test_pim_refusal_is_not_an_image_and_is_not_cached(self):
        result, _ = self._fetch(response=image_response(status=401, content_type='text/html'))
        self.assertIsNone(result)

        result, get = self._fetch()
        self.assertIsNotNone(result)
        get.assert_called_once()

    def test_a_non_image_body_is_refused(self):
        result, _ = self._fetch(response=image_response(content_type='text/html'))

        self.assertIsNone(result)

    def test_network_failure_is_none_not_an_exception(self):
        with patch('main_product_manager.utils.site') as site, \
                patch('main_product_manager.utils.httpx.get', side_effect=httpx.ConnectError('down')):
            site.get.return_value = FILE_RECORD
            self.assertIsNone(fetch_pim_image('f-1'))

    def test_a_malformed_id_or_size_never_reaches_pim(self):
        for file_id, size in (('../api/User', 'medium'), ('f-1', 'huge'), ('', 'medium'), (None, 'small')):
            with self.subTest(file_id=file_id, size=size):
                result, get = self._fetch(file_id=file_id, size=size)
                self.assertIsNone(result)
                get.assert_not_called()
                self.assertIsNone(pim_image_url(file_id, size))


@override_settings(CACHES=LOCMEM, PIM_HOST='pim.test', PIM_TOKEN='secret-token')
class PimImageViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)

    def test_serves_the_bytes_with_a_private_cache_header(self):
        with patch('product.views.fetch_pim_image', return_value=(b'img', 'image/png')):
            response = self.client.get(pim_image_url('f-1'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'img')
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['Cache-Control'], 'private, max-age=86400')

    def test_no_image_is_a_404(self):
        with patch('product.views.fetch_pim_image', return_value=None):
            response = self.client.get(pim_image_url('f-1'))

        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_turned_away_by_the_login_gate(self):
        self.client.logout()
        with patch('product.views.fetch_pim_image') as fetch:
            response = self.client.get(pim_image_url('f-1'))

        self.assertEqual(response.status_code, 302)
        fetch.assert_not_called()

    def test_photo_column_links_to_the_proxy_without_touching_the_network(self):
        """Отрисовка страницы в PIM не ходит — за байтами придёт браузер."""
        Product.objects.create(pim_id='pmp-1', number='SKU-1', name='Смеситель',
                               raw_data={'name': 'Смеситель', 'mainImageId': 'f-1'})
        self.client.get(reverse('products'), {'columns': ['photo']}, HTTP_HX_REQUEST='true')

        with patch('main_product_manager.utils.site') as site, \
                patch('main_product_manager.utils.httpx.get') as get:
            response = self.client.get(reverse('products'))

        self.assertContains(response, f'src="{pim_image_url("f-1")}"')
        site.get.assert_not_called()
        get.assert_not_called()
