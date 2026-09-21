"""Выбор колонок и строки поставщиков на товарной странице — перенос со старой главной."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier
from supplier_product_manager.models import SupplierProduct

from product.columns import DEFAULT_COLUMNS, load_columns, normalize_columns
from product.models import Product

# Предпочтения живут в кэше. Свой locmem на класс — иначе выбор из одного теста
# доживал бы в общем Redis до следующего прогона.
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'product-columns-tests'}}


@override_settings(CACHES=LOCMEM)
class ColumnPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)
        self.product = Product.objects.create(
            pim_id='pmp-1', number='SKU-1', name='Смеситель',
            raw_data={'name': 'Смеситель', 'tag': ['хит', 'новинка'], 'ean': '4600000000001'},
        )

    def test_nothing_chosen_gives_the_defaults(self):
        self.assertEqual(load_columns(self.user), DEFAULT_COLUMNS)

    def test_unknown_and_retired_keys_are_dropped(self):
        """manufacturer и прочие поля, которые удаляет Phase 2, в каталог не входят."""
        self.assertEqual(normalize_columns(['manufacturer', 'weight', 'kaspi_price']),
                         ['kaspi_price'])

    def test_choosing_nothing_falls_back_to_the_defaults(self):
        """Снятые все галочки приходят одним пустым columns — это явный выбор."""
        self.client.get(reverse('products'), {'columns': ['']}, HTTP_HX_REQUEST='true')

        self.assertEqual(load_columns(self.user), DEFAULT_COLUMNS)

    def test_the_choice_is_saved_and_survives_the_next_request(self):
        self.client.get(reverse('products'), {'columns': ['kaspi_price', 'tags']},
                        HTTP_HX_REQUEST='true')

        response = self.client.get(reverse('products'))

        self.assertEqual(response.context['selected_columns'], ['tags', 'kaspi_price'])

    def test_the_choice_does_not_drop_the_current_filter(self):
        """Выбор колонок едет тем же hx-get, что и фильтр, и не должен его стирать."""
        Product.objects.create(pim_id='pmp-2', number='SKU-2', name='Лампа',
                               raw_data={'name': 'Лампа'})

        response = self.client.get(reverse('products'),
                                   {'columns': ['stock'], 'search': 'SKU-1'},
                                   HTTP_HX_REQUEST='true')

        self.assertEqual([row.record.pk for row in response.context['table'].rows],
                         [self.product.pk])

    def test_optional_product_columns_are_hidden_by_default(self):
        response = self.client.get(reverse('products'))

        self.assertNotContains(response, '4600000000001')
        self.assertNotContains(response, 'новинка')

    def test_optional_product_columns_show_pim_data_when_chosen(self):
        self.client.get(reverse('products'), {'columns': ['tags', 'ean']}, HTTP_HX_REQUEST='true')

        response = self.client.get(reverse('products'))

        self.assertContains(response, 'хит, новинка')
        self.assertContains(response, '4600000000001')

    def test_the_picker_is_on_the_page_with_the_saved_choice_ticked(self):
        response = self.client.get(reverse('products'))

        content = response.content.decode()
        self.assertIn('id="product-columns"', content)
        self.assertRegex(content, r'value="prime_cost"[^>]*checked')
        self.assertNotRegex(content, r'value="kaspi_price"[^>]*checked')


@override_settings(CACHES=LOCMEM)
class SupplierRowsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(
            name='Поставщик', msg_available='В наличии', msg_navailable='Под заказ',
        )
        self.product = Product.objects.create(pim_id='pmp-1', number='SKU-1', name='Смеситель')
        self.row = MainProduct.objects.create(
            product=self.product, supplier=self.supplier, article='A1', name='Смеситель K1',
            stock=4, prime_cost=Decimal('120.00'), kaspi_price=Decimal('777.00'),
        )

    def _fragment(self):
        return self.client.get(reverse('product-suppliers', kwargs={'pk': self.product.pk}))

    def _choose(self, *columns):
        self.client.get(reverse('products'), {'columns': list(columns)}, HTTP_HX_REQUEST='true')

    def test_defaults_show_stock_message_and_the_cart_action(self):
        response = self._fragment()

        self.assertContains(response, 'В наличии')
        self.assertContains(response, reverse('cart-item-quick-add', args=[self.row.pk]))
        self.assertContains(response, reverse('mainproduct-info', args=[self.row.pk]))

    def test_zero_stock_shows_the_out_of_stock_message(self):
        self.row.stock = 0
        self.row.save()

        self.assertContains(self._fragment(), 'Под заказ')

    def test_null_stock_is_no_data_not_a_supplier_message(self):
        """NULL — «ни разу не синхронизировался», это не «под заказ»."""
        self.row.stock = None
        self.row.save()

        response = self._fragment()

        self.assertContains(response, 'Нет данных')
        self.assertNotContains(response, 'Под заказ')

    def test_a_chosen_price_column_appears(self):
        self.assertNotContains(self._fragment(), '777,00')

        self._choose('supplier', 'kaspi_price')

        self.assertContains(self._fragment(), '777,00')

    def test_supplier_price_comes_from_the_latest_price_row(self):
        SupplierProduct.objects.create(main_product=self.row, supplier=self.supplier,
                                       article='A1', name='x', supplier_price=Decimal('55.00'))
        self._choose('supplier_product_price')

        self.assertContains(self._fragment(), '55,00')

    def test_supplier_fields_are_choosable(self):
        self._choose('supplier__msg_navailable')

        self.assertContains(self._fragment(), 'Под заказ')

    def test_choosing_only_product_columns_keeps_the_supplier_table_usable(self):
        self._choose('tags')

        self.assertContains(self._fragment(), 'Поставщик')
