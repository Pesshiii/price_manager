from contextlib import contextmanager
from unittest.mock import patch

import httpx
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from pim_api import FlatEntity

from product.models import Product
from product.pim_content import (
    PimUnavailable, characteristics, clean_description, fetch_flat_product, other_fields,
    pim_product_url, description_html,
)

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

_DIMS = {'id': 'g-dims', 'name': 'Размеры и вес', 'sortOrder': 10}
_PACK = {'id': 'g-pack', 'name': 'Упаковка', 'sortOrder': 20}

# Ответ Product/{id} с Flatten-Attributes — в той форме, в какой его отдаёт PIM:
# у атрибута с единицей рядом свой `<code>Unit` (unitIdField) и `<code>UnitData`.
FLAT = {
    'id': 'pim-1',
    'ean': '4600000000001',
    'tag': ['хит', 'новинка'],
    'note': '',
    'countryOfOriginName': None,
    'attributesDefs': {
        'pack_lengthUnit': {'type': 'link', 'label': 'Длина упаковки (Unit)', 'unitIdField': True,
                            'attributeGroup': _PACK, 'sortOrder': 220},
        'pack_length': {'type': 'float', 'label': 'Длина упаковки (Float)', 'attributeGroup': _PACK,
                        'sortOrder': 220, 'sortOrderInAttributeGroup': 0},
        'weightUnit': {'type': 'link', 'label': 'Вес (Unit)', 'unitIdField': True,
                       'attributeGroup': _DIMS, 'sortOrder': 190},
        'weight': {'type': 'float', 'label': 'Вес (Float)', 'attributeGroup': _DIMS, 'sortOrder': 190},
        'length': {'type': 'int', 'label': 'Длина', 'attributeGroup': _DIMS, 'sortOrder': 10},
        'chestny_znak': {'type': 'bool', 'label': 'Честный знак', 'attributeGroup': {}, 'sortOrder': 1130},
        'contents': {'type': 'text', 'label': 'Комплектация', 'attributeGroup': _PACK, 'sortOrder': 600},
        'certificate': {'type': 'url', 'label': 'Сертификат', 'attributeGroup': _PACK, 'sortOrder': 2490},
        'pack_type': {'type': 'varchar', 'label': 'Тип упаковки', 'attributeGroup': _PACK, 'sortOrder': 280},
        'setProducts': {'type': 'linkMultiple', 'label': 'Set Products', 'attributeGroup': {}, 'sortOrder': 1},
    },
    'pack_length': 35.5,
    'pack_lengthUnitData': {'name': 'Сантиметр', 'symbol': 'см'},
    'weight': 0.0869,
    'weightUnitData': {'name': 'Килограмм', 'symbol': 'кг'},
    'length': 350,
    'chestny_znak': False,
    'contents': 'Киянка - 1 шт\nЧехол - 1 шт',
    'certificate': 'https://example.com/cert.pdf',
    'pack_type': '  ',
    'setProducts': ['x'],
}


@contextmanager
def _site_get(**kwargs):
    """Подменяет site.get клиента PIM; отдаёт мок самого get.

    Патчится весь site: SiteAPI — модель pydantic, атрибут на экземпляре не подменить.
    """
    with patch('product.pim_content.pim_client.site') as site:
        site.get.configure_mock(**kwargs)
        yield site.get


def _status_error(code):
    request = httpx.Request('GET', 'https://pim.test/api/Product/pim-1')
    return httpx.HTTPStatusError('err', request=request, response=httpx.Response(code, request=request))


class CleanDescriptionTests(SimpleTestCase):
    def test_keeps_markup_and_drops_scripts_images_and_empty_lists(self):
        html = clean_description('<p>Текст</p><h4>Преимущества</h4><ul></ul>'
                                 '<script>alert(1)</script><img src="https://pim/x.png"><ul><li>Раз</li></ul>')
        self.assertEqual(html, '<p>Текст</p><h4>Преимущества</h4><ul><li>Раз</li></ul>')

    def test_heading_left_without_content_is_dropped(self):
        html = clean_description('<p>Текст</p><h4>Преимущества</h4><ul></ul>'
                                 '<h4>Использование</h4><p>Так</p><h4>Пусто</h4><ul> </ul>')
        self.assertEqual(html, '<p>Текст</p><h4>Использование</h4><p>Так</p>')

    def test_plain_text_keeps_its_line_breaks_escaped(self):
        self.assertEqual(clean_description('a < b\nвторая'), '<p>a &lt; b<br>вторая</p>')

    def test_empty_or_markup_only_is_blank(self):
        self.assertEqual(clean_description(None), '')
        self.assertEqual(clean_description('<p> </p>'), '')

    def test_description_html_repeating_the_name_is_hidden(self):
        self.assertEqual(description_html({'description': '<p>Молоток</p>'}, 'Молоток'), '')
        self.assertEqual(description_html({'description': 'Кованый'}, 'Молоток'), '<p>Кованый</p>')


class CharacteristicsTests(SimpleTestCase):
    def test_groups_in_pim_order_with_units_and_formatted_values(self):
        groups = characteristics(FLAT)

        self.assertEqual([g['name'] for g in groups], ['Размеры и вес', 'Упаковка', 'Без группы'])
        dims = [(i['label'], i['value'], i['unit']) for i in groups[0]['items']]
        self.assertEqual(dims, [('Длина', '350', None), ('Вес', '0,0869', 'кг')])
        pack = {i['label']: i for i in groups[1]['items']}
        self.assertEqual(pack['Длина упаковки']['value'], '35,5')
        self.assertEqual(pack['Длина упаковки']['unit'], 'см')
        self.assertEqual(pack['Комплектация']['kind'], 'multiline')
        self.assertEqual(pack['Сертификат']['kind'], 'url')
        self.assertNotIn('Тип упаковки', pack)  # пустое значение
        self.assertEqual([(i['label'], i['value']) for i in groups[2]['items']], [('Честный знак', 'нет')])

    def test_unit_fields_and_links_are_not_characteristics(self):
        labels = {i['label'] for g in characteristics(FLAT) for i in g['items']}
        self.assertFalse({'Длина упаковки (Unit)', 'Set Products'} & labels)

    def test_product_without_attributes_has_none(self):
        self.assertEqual(characteristics({'id': 'x'}), [])

    def test_other_fields_skip_blanks_and_join_lists(self):
        self.assertEqual(other_fields(FLAT), [('EAN', '4600000000001'), ('Теги', 'хит, новинка')])


class PimProductUrlTests(SimpleTestCase):
    @override_settings(PIM_HOST='pim.example.kz')
    def test_links_to_the_record_in_pim(self):
        self.assertEqual(pim_product_url('abc'), 'https://pim.example.kz/#Product/view/abc')

    @override_settings(PIM_HOST='http://pim.invalid/')
    def test_host_with_scheme_is_tolerated(self):
        self.assertEqual(pim_product_url('abc'), 'https://pim.invalid/#Product/view/abc')

    def test_no_id_no_link(self):
        self.assertIsNone(pim_product_url(None))


class FlatEntityTests(SimpleTestCase):
    def test_sends_the_flatten_header_along_with_the_token(self):
        with patch('pim_api.httpx.get') as get:
            FlatEntity(name='Product', id='p1').get(prefix='https://pim.test/api/', headers={'Authorization-Token': 't'})

        self.assertEqual(get.call_args.kwargs['url'], 'https://pim.test/api/Product/p1')
        self.assertEqual(get.call_args.kwargs['headers'],
                         {'Authorization-Token': 't', 'Flatten-Attributes': 'true'})


@override_settings(CACHES=LOCMEM)
class FetchFlatProductTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_second_call_is_served_from_cache_and_refresh_goes_to_pim(self):
        with _site_get(return_value=FLAT) as get:
            self.assertEqual(fetch_flat_product('pim-1'), FLAT)
            fetch_flat_product('pim-1')
            self.assertEqual(get.call_count, 1)
            fetch_flat_product('pim-1', refresh=True)
            self.assertEqual(get.call_count, 2)
        self.assertIsInstance(get.call_args.args[0], FlatEntity)

    def test_not_found_is_none(self):
        with _site_get(side_effect=_status_error(404)):
            self.assertIsNone(fetch_flat_product('pim-1'))

    def test_failure_serves_the_last_answer_even_on_refresh(self):
        with _site_get(return_value=FLAT):
            fetch_flat_product('pim-1')
        with _site_get(side_effect=httpx.ConnectError('down')):
            self.assertEqual(fetch_flat_product('pim-1', refresh=True), FLAT)

    def test_failure_without_cache_raises(self):
        with _site_get(side_effect=_status_error(500)):
            with self.assertRaises(PimUnavailable):
                fetch_flat_product('pim-1')


@override_settings(CACHES=LOCMEM, PIM_HOST='pim.example.kz')
class CardPimContentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(User.objects.create_user(username='u', password='pw'))
        self.product = Product.objects.create(number='SKU-1', name='Киянка', raw_data={
            'id': 'pim-1', 'name': 'Киянка', 'description': 'Резиновая, 680 г',
            'longDescription': '<p>Для сборки мебели</p><script>alert(1)</script>',
        })

    def test_card_shows_clean_descriptions_pim_link_and_lazy_panel(self):
        response = self.client.get(reverse('product-detail', kwargs={'pk': self.product.pk}))

        self.assertContains(response, '<p>Резиновая, 680 г</p>')
        self.assertContains(response, '<p>Для сборки мебели</p>')
        self.assertNotContains(response, 'alert(1)')
        self.assertContains(response, 'https://pim.example.kz/#Product/view/pim-1')
        self.assertContains(response, reverse('product-pim', kwargs={'pk': self.product.pk}))

    def test_card_without_pim_data_does_not_ask_pim(self):
        product = Product.objects.create(number='SKU-2', name='Без PIM')

        response = self.client.get(reverse('product-detail', kwargs={'pk': product.pk}))

        self.assertNotContains(response, reverse('product-pim', kwargs={'pk': product.pk}))
        self.assertNotContains(response, 'Открыть в PIM')

    def test_panel_renders_grouped_characteristics(self):
        with _site_get(return_value=FLAT):
            response = self.client.get(reverse('product-pim', kwargs={'pk': self.product.pk}))

        self.assertContains(response, 'Размеры и вес')
        self.assertContains(response, '0,0869 кг')
        self.assertContains(response, 'https://example.com/cert.pdf')
        self.assertContains(response, '4600000000001')

    def test_panel_says_so_when_pim_is_down(self):
        with _site_get(side_effect=httpx.ConnectError('down')):
            response = self.client.get(reverse('product-pim', kwargs={'pk': self.product.pk}))

        self.assertContains(response, 'PIM не ответил')

    def test_panel_for_a_product_without_pim_never_calls_it(self):
        product = Product.objects.create(number='SKU-2', raw_data={'name': 'Без id'})

        with _site_get() as get:
            response = self.client.get(reverse('product-pim', kwargs={'pk': product.pk}))

        get.assert_not_called()
        self.assertContains(response, 'Товара нет в PIM')
