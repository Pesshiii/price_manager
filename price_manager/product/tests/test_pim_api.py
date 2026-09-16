"""Тесты клиента pim_api — того, что нужно живой ноге фильтра по PIM.

pim_api не приложение Django, тестов у него своих нет, поэтому они живут здесь,
рядом с PimClientWiringTests, — у потребителя.
"""

from unittest.mock import patch
from urllib.parse import parse_qsl, urlparse

import httpx
from django.test import SimpleTestCase

from pim_api import Asc, EntityList, ListResult, Ordering, SiteAPI, Where, fetch_list


def _response(payload=None):
    """httpx.Response с привязанным request.

    Без него raise_for_status() в SiteAPI.get падает с RuntimeError, а не
    отдаёт тело — ответ без запроса httpx считает неполным.
    """
    return httpx.Response(
        200,
        json=payload if payload is not None else {},
        request=httpx.Request('GET', 'https://pim.test/api/Product'),
    )


def _wire_params(params: dict) -> list[tuple[str, str]]:
    """Параметры так, как они уходят на провод — повторы не схлопываются."""
    url = httpx.Request('GET', 'https://pim.test/api/Product', params=params).url
    return parse_qsl(urlparse(str(url)).query, keep_blank_values=True)


class WhereEncodingTests(SimpleTestCase):
    def test_scalar_value_keeps_the_original_key(self):
        """Скалярная ветка обязана остаться прежней.

        По ней ходят все существующие вызовы с `equals`; сменить ключ здесь —
        сломать привязку товаров к PIM.
        """
        self.assertEqual(
            Where(attribute='number', type='equals', value='N1').get(0),
            {'where[0][attribute]': 'number', 'where[0][type]': 'equals', 'where[0][value]': 'N1'},
        )

    def test_list_value_uses_php_array_notation(self):
        encoded = Where(attribute='categories', type='linkedWith', value=['c1', 'c2']).get(0)

        self.assertEqual(encoded['where[0][value][]'], ['c1', 'c2'])
        self.assertNotIn('where[0][value]', encoded)

    def test_list_value_survives_url_encoding_as_a_repeated_param(self):
        """Ключ должен уйти на провод повторяющимся, а не строкой со списком.

        Это то, что реально разбирает PIM, поэтому проверяем на собранном URL,
        а не на словаре: "['c1', 'c2']" в одном параметре прошло бы проверку
        словаря и не прошло бы у PIM.
        """
        query = EntityList(
            name='Product',
            where=[Where(attribute='categories', type='linkedWith', value=['c1', 'c2'])],
        )
        with patch('httpx.get', return_value=_response()) as mock_get:
            query.get(prefix='https://pim.test/api/', headers={})

        pairs = _wire_params(mock_get.call_args.kwargs['params'])

        self.assertIn(('where[0][value][]', 'c1'), pairs)
        self.assertIn(('where[0][value][]', 'c2'), pairs)
        self.assertEqual(sum(1 for k, _ in pairs if k == 'where[0][value][]'), 2)

    def test_value_none_emits_no_value_key(self):
        encoded = Where(attribute='number', type='isNull').get(0)
        self.assertNotIn('where[0][value]', encoded)
        self.assertNotIn('where[0][value][]', encoded)


class EntityListParamsTests(SimpleTestCase):
    def _sent_params(self, query: EntityList) -> dict:
        with patch('httpx.get', return_value=_response()) as mock_get:
            query.get(prefix='https://pim.test/api/', headers={})
        return mock_get.call_args.kwargs['params']

    def test_paging_params_are_emitted(self):
        params = self._sent_params(EntityList(name='Product', offset=40, maxSize=20))

        self.assertEqual(params['offset'], 40)
        self.assertEqual(params['maxSize'], 20)

    def test_paging_params_absent_when_unset(self):
        """Запрос без пагинации должен уйти ровно таким, каким уходил раньше."""
        params = self._sent_params(EntityList(name='Product', select=['id']))

        self.assertNotIn('offset', params)
        self.assertNotIn('maxSize', params)
        self.assertEqual(params, {'select': 'id'})

    def test_ordering_is_emitted(self):
        """`ordering` был объявлен на модели, но НИКОГДА не попадал в запрос.

        Поле-фантом: присвоение проходило, сортировка не применялась. Ни один
        существующий вызов его не передаёт, поэтому включение ничего не ломает.
        """
        params = self._sent_params(
            EntityList(name='Product', ordering=Ordering(sortBy='name', asc=Asc.ASC))
        )

        self.assertEqual(params['sortBy'], 'name')
        self.assertIs(params['asc'], True)


class SiteApiTimeoutTests(SimpleTestCase):
    def setUp(self):
        self.site = SiteAPI(token='t', host='pim.test', timeout=5.0)

    def test_per_call_timeout_overrides_the_default(self):
        with patch('httpx.get', return_value=_response()) as mock_get:
            self.site.get(EntityList(name='Product'), timeout=1.5)

        self.assertEqual(mock_get.call_args.kwargs['timeout'], 1.5)

    def test_default_timeout_is_used_when_not_overridden(self):
        with patch('httpx.get', return_value=_response()) as mock_get:
            self.site.get(EntityList(name='Product'))

        self.assertEqual(mock_get.call_args.kwargs['timeout'], 5.0)


class FetchListTests(SimpleTestCase):
    def setUp(self):
        self.site = SiteAPI(token='t', host='pim.test')

    def _paged(self, total, ids, page_size):
        """Отдаёт страницы так же, как PIM: срез по offset/maxSize плюс total."""
        def fake_get(method, timeout=None):
            offset = method.offset or 0
            size = method.maxSize or len(ids)
            return {'total': total, 'list': [{'id': i} for i in ids[offset:offset + size]]}
        return fake_get

    def test_walks_every_page(self):
        ids = [f'id{i}' for i in range(250)]
        with patch.object(SiteAPI, 'get', side_effect=self._paged(250, ids, 100)):
            result = fetch_list(self.site, EntityList(name='Product'), page_size=100)

        self.assertIsInstance(result, ListResult)
        self.assertEqual(result.total, 250)
        self.assertEqual(len(result.items), 250)
        self.assertFalse(result.truncated)

    def test_single_page_fits(self):
        ids = ['a', 'b']
        with patch.object(SiteAPI, 'get', side_effect=self._paged(2, ids, 200)):
            result = fetch_list(self.site, EntityList(name='Product'))

        self.assertEqual([i['id'] for i in result.items], ['a', 'b'])
        self.assertFalse(result.truncated)

    def test_max_items_caps_and_reports_truncation(self):
        """Обрезка обязана быть видимой.

        Молча вернуть префикс — ровно тот баг, ради которого заводилась
        пагинация.
        """
        ids = [f'id{i}' for i in range(500)]
        with patch.object(SiteAPI, 'get', side_effect=self._paged(500, ids, 100)):
            result = fetch_list(self.site, EntityList(name='Product'), page_size=100, max_items=150)

        self.assertEqual(len(result.items), 150)
        self.assertEqual(result.total, 500)
        self.assertTrue(result.truncated)

    def test_short_read_is_also_truncated(self):
        """PIM пообещал больше, чем отдал — это тоже неполный набор."""
        def liar(method, timeout=None):
            offset = method.offset or 0
            return {'total': 100, 'list': [{'id': 'a'}] if offset == 0 else []}

        with patch.object(SiteAPI, 'get', side_effect=liar):
            result = fetch_list(self.site, EntityList(name='Product'))

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.total, 100)
        self.assertTrue(result.truncated)

    def test_empty_result(self):
        with patch.object(SiteAPI, 'get', return_value={'total': 0, 'list': []}):
            result = fetch_list(self.site, EntityList(name='Product'))

        self.assertEqual(result.items, [])
        self.assertFalse(result.truncated)

    def test_does_not_loop_forever_on_an_empty_page(self):
        """Иначе рассогласованный total крутит цикл до таймаута задачи."""
        with patch.object(SiteAPI, 'get', return_value={'total': 999, 'list': []}) as mock_get:
            result = fetch_list(self.site, EntityList(name='Product'))

        self.assertEqual(mock_get.call_count, 1)
        self.assertTrue(result.truncated)

    def test_caller_paging_fields_are_ignored(self):
        """Страницами управляет fetch_list, а не переданный запрос."""
        ids = [f'id{i}' for i in range(5)]
        seen = []

        def record(method, timeout=None):
            seen.append((method.offset, method.maxSize))
            offset = method.offset or 0
            return {'total': 5, 'list': [{'id': i} for i in ids[offset:offset + method.maxSize]]}

        with patch.object(SiteAPI, 'get', side_effect=record):
            fetch_list(
                self.site,
                EntityList(name='Product', offset=999, maxSize=1),
                page_size=2,
            )

        self.assertEqual(seen, [(0, 2), (2, 2), (4, 2)])

    def test_query_fields_are_preserved_across_pages(self):
        captured = []

        def record(method, timeout=None):
            captured.append(method)
            return {'total': 1, 'list': [{'id': 'a'}]}

        with patch.object(SiteAPI, 'get', side_effect=record):
            fetch_list(
                self.site,
                EntityList(
                    name='Product',
                    select=['id', 'name'],
                    where=[Where(attribute='categories', type='linkedWith', value=['c1'])],
                ),
                page_size=50,
            )

        self.assertEqual(captured[0].name, 'Product')
        self.assertEqual(captured[0].select, ['id', 'name'])
        self.assertEqual(captured[0].where[0].value, ['c1'])

    def test_timeout_is_passed_through_to_every_page(self):
        def record(method, timeout=None):
            self.assertEqual(timeout, 1.5)
            return {'total': 0, 'list': []}

        with patch.object(SiteAPI, 'get', side_effect=record):
            fetch_list(self.site, EntityList(name='Product'), timeout=1.5)
