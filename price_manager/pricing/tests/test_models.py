from django.test import TestCase, override_settings

from .fixtures import make_price_type


@override_settings(SECURE_SSL_REDIRECT=False)
class PriceTypeStrTests(TestCase):
    def test_str_returns_label(self):
        pt = make_price_type(name='закупочная', label='Закупочная цена')
        self.assertEqual(str(pt), 'Закупочная цена')
