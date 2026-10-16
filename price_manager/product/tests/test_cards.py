"""Режим карточек на товарной странице и выпадающий список поставщиков в карточке."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from product.columns import load_view_mode, save_columns, save_view_mode
from product.models import Brand, Category, Product, ProductPhoto
from product.tables import suppliers_label
from product.tests.test_set_costs import SetFixture

# Вид выдачи и колонки живут в кэше. Свой locmem — иначе сохранённые здесь
# «карточки» пользователя доживали бы в общем Redis до следующего прогона, и
# тесты таблицы без своего кэша получали бы карточки.
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'product-cards-tests'}}

# Разметка, а не имена классов: стили страницы называют те же классы.
CARD = 'class="product-card"'
GROUP = 'class="product-group-path products-card-group"'


class CardsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)

    def page(self, params=None, htmx=False):
        headers = {'HTTP_HX_REQUEST': 'true'} if htmx else {}
        return self.client.get(reverse('products'), params or {}, **headers)


@override_settings(CACHES=LOCMEM)
class ViewModeTests(CardsTestCase):
    def setUp(self):
        super().setUp()
        Product.objects.create(number='SKU-1', name='Смеситель', raw_data={'name': 'Смеситель'})

    def test_table_is_the_default(self):
        response = self.page()

        self.assertEqual(response.context['view_mode'], 'table')
        self.assertNotContains(response, CARD)
        self.assertContains(response, 'class="table products-table')

    def test_toggle_renders_cards_and_the_mode_is_saved(self):
        response = self.page({'view': 'cards'}, htmx=True)

        self.assertTemplateUsed(response, 'product/partials/table.html')
        self.assertContains(response, CARD)
        self.assertNotContains(response, 'class="table products-table')
        self.assertEqual(load_view_mode(self.user), 'cards')

        # Перезагрузка страницы без view= — сохранённые карточки.
        response = self.page()
        self.assertEqual(response.context['view_mode'], 'cards')
        self.assertContains(response, CARD)

    def test_search_and_filters_keep_the_saved_mode(self):
        """view= шлёт только переключатель — поиск его не несёт."""
        save_view_mode(self.user, 'cards')

        response = self.page({'search': 'SKU-1'}, htmx=True)

        self.assertContains(response, CARD)

    def test_unknown_mode_is_the_table(self):
        save_view_mode(self.user, 'cards')

        response = self.page({'view': 'mosaic'}, htmx=True)

        self.assertEqual(response.context['view_mode'], 'table')
        self.assertEqual(load_view_mode(self.user), 'table')

    def test_toggle_marks_the_active_mode(self):
        save_view_mode(self.user, 'cards')

        html = self.page().content.decode()

        self.assertRegex(html, r'class="btn btn-outline-secondary active"\s+aria-pressed="true"\s+'
                               r'title="Карточки"')

    def test_cards_page_holds_24_and_the_table_25(self):
        Product.objects.bulk_create(
            Product(number=f'BULK-{i}', name=f'Товар {i}') for i in range(40))

        self.assertEqual(len(self.page().context['table'].page.object_list), 25)
        save_view_mode(self.user, 'cards')
        response = self.page()
        self.assertEqual(len(response.context['table'].page.object_list), 24)
        self.assertEqual(response.content.decode().count(CARD), 24)


@override_settings(CACHES=LOCMEM)
class CardContentTests(CardsTestCase):
    def setUp(self):
        super().setUp()
        save_view_mode(self.user, 'cards')
        self.brand = Brand.objects.create(pim_id='br-1', name='Grohe')
        self.category = Category.objects.create(name='Сантехника')
        self.supplier = Supplier.objects.create(name='Поставщик')
        self.product = Product.objects.create(
            pim_id='pmp-1', number='SKU-1', name='Смеситель', brand=self.brand,
            raw_data={'name': 'Смеситель', 'tag': ['хит']})
        self.product.categories.add(self.category)
        MainProduct.objects.create(product=self.product, supplier=self.supplier, article='A1',
                                   name='Смеситель', stock=4, prime_cost=Decimal('120.00'))

    def test_card_shows_what_the_table_row_shows(self):
        html = self.page().content.decode()

        self.assertIn('Grohe · Сантехника', html)
        self.assertIn('SKU-1', html)
        self.assertIn('120,00', html)
        self.assertIn('Остаток 4', html)
        self.assertIn('1 поставщик', html)
        self.assertIn(reverse('product-detail', kwargs={'pk': self.product.pk}), html)

    def test_cards_are_grouped_under_category_headers(self):
        Product.objects.create(number='SKU-2', name='Лампа')

        html = self.page().content.decode()

        self.assertEqual(html.count(GROUP), 2)
        self.assertIn('<span>Сантехника</span>', html)
        self.assertIn('<span>Без категории</span>', html)
        self.assertLess(html.index('Сантехника</span>'), html.index('SKU-1'))

    def test_sort_drops_the_groups_and_is_selected_in_the_list(self):
        html = self.page({'sort': '-supplier_count'}).content.decode()

        self.assertNotIn(GROUP, html)
        self.assertIn('<option value="-supplier_count" selected>', html)

    def test_sort_list_is_shown_only_with_cards(self):
        self.assertContains(self.page(), 'class="products-sort"')
        save_view_mode(self.user, 'table')
        self.assertNotContains(self.page(), 'class="products-sort"')

    def test_stock_null_and_zero_differ(self):
        unsynced = Product.objects.create(number='SKU-2', name='Без данных')
        MainProduct.objects.create(product=unsynced, supplier=self.supplier, article='A2',
                                   name='Без данных', stock=None)
        empty = Product.objects.create(number='SKU-3', name='Пусто')
        MainProduct.objects.create(product=empty, supplier=self.supplier, article='A3',
                                   name='Пусто', stock=0)

        html = self.page().content.decode()

        self.assertIn('Нет данных</span>', html)
        self.assertIn('Нет в наличии</span>', html)

    def test_no_photo_is_a_strip_not_a_blank_frame(self):
        self.assertContains(self.page(), 'product-card-photo is-empty')

    def test_tags_show_only_when_chosen_in_columns(self):
        self.assertNotContains(self.page(), 'Теги:')
        save_columns(self.user, ['tags', 'supplier'])
        self.assertContains(self.page(), '<span>Теги:</span> хит')

    def test_photos_take_one_query_for_all_cards(self):
        public = 'https://pim.example.kz/sharings/s-1.jpg'

        def add_product(number):
            product = Product.objects.create(number=number, name=number, raw_data={'id': f'p-{number}'})
            ProductPhoto.objects.create(product=product, pim_file_id=f'f-{number}', public_url=public)

        add_product('PH-1')
        with CaptureQueriesContext(connection) as one_card:
            self.page()
        add_product('PH-2')
        add_product('PH-3')
        with CaptureQueriesContext(connection) as three_cards:
            response = self.page()

        self.assertEqual(response.content.decode().count(f'<img src="{public}"'), 3)
        self.assertEqual(len(three_cards), len(one_card))

    def test_card_has_no_ids_to_duplicate(self):
        html = self.page().content.decode()
        start = html.index(CARD)
        card = html[start:html.index('</article>', start)]

        self.assertNotIn(' id="', card)


class SuppliersLabelTests(TestCase):
    def test_russian_plural(self):
        cases = {0: 'Нет поставщиков', 1: '1 поставщик', 2: '2 поставщика', 4: '4 поставщика',
                 5: '5 поставщиков', 11: '11 поставщиков', 12: '12 поставщиков',
                 21: '21 поставщик', 22: '22 поставщика', 112: '112 поставщиков'}
        for count, label in cases.items():
            with self.subTest(count=count):
                self.assertEqual(suppliers_label(count), label)


@override_settings(CACHES=LOCMEM)
class CompactSuppliersTests(CardsTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(name='Альфа', msg_navailable='Под заказ')
        self.product = Product.objects.create(number='SKU-1', name='Смеситель')

    def compact(self, product=None):
        url = reverse('product-suppliers', kwargs={'pk': (product or self.product).pk})
        return self.client.get(url, {'compact': '1'}).content.decode()

    def test_row_carries_cost_stock_and_the_cart_button(self):
        row = MainProduct.objects.create(product=self.product, supplier=self.supplier, article='A1',
                                         name='Смеситель', stock=0, prime_cost=Decimal('120.00'),
                                         basic_price=Decimal('150.00'))

        html = self.compact()

        self.assertIn('Альфа', html)
        self.assertIn('120,00', html)
        self.assertIn('нет в наличии', html)
        self.assertIn('title="Под заказ"', html)
        self.assertIn(reverse('cart-item-quick-add', args=[row.pk]), html)
        self.assertIn(reverse('mainproduct-info', kwargs={'pk': row.pk}), html)
        self.assertNotIn('suppliers-table', html)

    def test_price_is_the_first_chosen_price_column(self):
        MainProduct.objects.create(product=self.product, supplier=self.supplier, article='A1',
                                   name='Смеситель', stock=2, prime_cost=Decimal('120.00'),
                                   basic_price=Decimal('150.00'), m_price=Decimal('170.00'))

        html = self.compact()
        self.assertIn('Себестоимость · Базовая цена', html)
        self.assertIn('150,00', html)
        self.assertNotIn('170,00', html)

        save_columns(self.user, ['supplier', 'm_price'])
        html = self.compact()
        self.assertIn('Себестоимость · Цена ИМ', html)
        self.assertIn('170,00', html)

    def test_no_price_chosen_shows_the_cost_alone(self):
        MainProduct.objects.create(product=self.product, supplier=self.supplier, article='A1',
                                   name='Смеситель', stock=2, prime_cost=Decimal('120.00'),
                                   basic_price=Decimal('150.00'))
        save_columns(self.user, ['supplier', 'stock'])

        html = self.compact()

        self.assertIn('<span>Себестоимость</span>', html)
        self.assertNotIn('150,00', html)
        self.assertNotIn('product-card-supplier-price', html)

    def test_no_rows_offers_to_add_one(self):
        html = self.compact()

        self.assertIn('Строк ГП нет', html)
        self.assertIn(f'{reverse("mainproduct-create")}?product={self.product.pk}', html)


@override_settings(CACHES=LOCMEM)
class CompactSetTests(SetFixture, CardsTestCase):
    def setUp(self):
        super().setUp()
        self.make_sets()

    def compact(self):
        url = reverse('product-suppliers', kwargs={'pk': self.kit.pk})
        return self.client.get(url, {'compact': '1'}).content.decode()

    def test_set_without_its_own_row_can_still_go_to_the_cart(self):
        html = self.compact()

        self.assertIn(reverse('cart-item-add-set', args=[self.kit.pk]), html)
        self.assertIn('480,00', html)
        self.assertNotIn('Строк ГП нет', html)

    def test_set_row_is_labelled_as_a_set(self):
        MainProduct.objects.create(product=self.kit, is_set=True, sku='KIT-1',
                                   article='KIT-1', name='Стеллаж')

        html = self.compact()

        self.assertIn('>Набор</a>', html)
        self.assertIn(reverse('cart-item-add-set', args=[self.kit.pk]), html)
