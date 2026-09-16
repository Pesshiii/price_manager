from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from product.models import Brand, Category, Product


class ProductPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)

        self.brand = Brand.objects.create(pim_id='br-1', name='Grohe')
        self.category = Category.objects.create(name='Сантехника')
        self.supplier = Supplier.objects.create(name='Поставщик')

        self.product = Product.objects.create(
            pim_id='pmp-1', number='SKU-1', name='Смеситель',
            brand=self.brand, raw_data={'name': 'Смеситель'},
        )
        self.product.categories.add(self.category)
        self.product.rebuild_search_vector()

        MainProduct.objects.create(
            product=self.product, supplier=self.supplier, article='A1', name='Смеситель',
            stock=4, prime_cost=Decimal('120.00'),
        )

    def test_anonymous_is_redirected_by_the_global_login_gate(self):
        self.client.logout()
        response = self.client.get(reverse('products'))
        self.assertEqual(response.status_code, 302)

    def test_page_renders(self):
        response = self.client.get(reverse('products'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'product/list.html')
        self.assertContains(response, 'SKU-1')
        self.assertContains(response, 'Grohe')

    def test_row_shows_aggregates_over_its_main_products(self):
        other = Supplier.objects.create(name='Второй')
        MainProduct.objects.create(
            product=self.product, supplier=other, article='A2', name='Смеситель',
            stock=6, prime_cost=Decimal('150.00'),
        )

        response = self.client.get(reverse('products'))
        row = response.context['table'].rows[0]

        self.assertEqual(row.record.supplier_count, 2)
        self.assertEqual(row.record.total_stock, 10)
        self.assertEqual(row.record.min_prime_cost, Decimal('120.00'))
        self.assertEqual(row.record.max_prime_cost, Decimal('150.00'))

    def test_product_appears_once_even_with_several_suppliers(self):
        other = Supplier.objects.create(name='Второй')
        MainProduct.objects.create(
            product=self.product, supplier=other, article='A2', name='Смеситель', stock=6,
        )

        response = self.client.get(reverse('products'))
        self.assertEqual(len(response.context['table'].rows), 1)

    def test_unlinked_main_products_are_counted_not_shown(self):
        """Невидимость принятая, но наблюдаемая (P1-G3).

        Без счётчика никто не узнает, что часть прайса выпала со страницы.
        """
        MainProduct.objects.create(product=None, supplier=self.supplier, article='X', name='Сирота')

        response = self.client.get(reverse('products'))

        self.assertEqual(response.context['unlinked_main_products'], 1)
        self.assertEqual(len(response.context['table'].rows), 1)
        self.assertNotContains(response, 'Сирота')

    def test_unsynced_products_are_counted(self):
        Product.objects.create(pim_id='pmp-2', number='SKU-2', raw_data={})

        response = self.client.get(reverse('products'))
        self.assertEqual(response.context['unsynced_products'], 1)

    def test_search_narrows_the_table(self):
        Product.objects.create(pim_id='pmp-3', number='SKU-OTHER', name='Лампа')

        response = self.client.get(reverse('products'), {'search': 'SKU-1'})

        self.assertEqual(len(response.context['table'].rows), 1)

    def test_search_input_carries_the_id_the_htmx_wiring_selects_on(self):
        """hx-include формы фильтров и hx-trigger строки поиска ссылаются на
        #products-search. С дефолтным id_search оба селектора молча не находят
        ничего: поиск не срабатывает, а применение фильтра стирает запрос.
        """
        response = self.client.get(reverse('products'))

        self.assertContains(response, 'id="products-search"')

    def test_filter_keeps_the_search_term(self):
        Product.objects.create(pim_id='pmp-3', number='SKU-OTHER', name='Лампа')

        response = self.client.get(
            reverse('products'), {'search': 'SKU-1', 'available': 'true'}
        )

        self.assertEqual(len(response.context['table'].rows), 1)
        self.assertEqual(response.context['filter'].data.get('search'), 'SKU-1')


class ProductFragmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(name='Поставщик')
        self.product = Product.objects.create(pim_id='pmp-1', number='SKU-1', name='Смеситель')

    def test_suppliers_fragment_lists_the_price_rows(self):
        MainProduct.objects.create(
            product=self.product, supplier=self.supplier, article='A1', name='Смеситель',
            stock=3, prime_cost=Decimal('99.00'),
        )

        response = self.client.get(reverse('product-suppliers', kwargs={'pk': self.product.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Поставщик')
        self.assertContains(response, 'A1')
        # Интерфейс русский: Django форматирует десятичные с запятой.
        self.assertContains(response, '99,00')

    def test_fragment_does_not_leak_template_comments_into_the_response(self):
        """Многострочный {# #} не комментарий — он утекает текстом в ответ.

        Django закрывает однострочный комментарий концом тега, а не концом
        строки, поэтому многострочный {# … #} отрисовывается как есть.
        """
        response = self.client.get(reverse('product-suppliers', kwargs={'pk': self.product.pk}))

        self.assertNotContains(response, '{#')
        self.assertNotContains(response, 'MainProduct здесь')

    def test_suppliers_fragment_handles_a_product_with_none(self):
        response = self.client.get(reverse('product-suppliers', kwargs={'pk': self.product.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ни один поставщик не привязан')

    def test_filter_fragment_redirects_a_non_htmx_request(self):
        response = self.client.get(reverse('product-filter'))
        self.assertEqual(response.status_code, 302)

    def test_filter_fragment_renders_for_htmx(self):
        response = self.client.get(reverse('product-filter'), HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'product/partials/filter.html')

    def test_htmx_request_returns_only_the_table_fragment(self):
        """Иначе в #products-table вставляется list.html целиком.

        И фильтр, и строка поиска бьют hx-get в 'products'. Без ветки на
        request.htmx ответом приходит вся страница и попадает внутрь таблицы —
        страница в странице.
        """
        response = self.client.get(reverse('products'), HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'product/partials/table.html')
        self.assertTemplateNotUsed(response, 'product/list.html')

    def test_plain_request_returns_the_whole_page(self):
        response = self.client.get(reverse('products'))

        self.assertTemplateUsed(response, 'product/list.html')

    def test_htmx_fragment_carries_no_second_filter_panel(self):
        """Фрагмент не должен тащить с собой панель фильтров и шапку."""
        response = self.client.get(reverse('products'), HTTP_HX_REQUEST='true')

        self.assertNotContains(response, 'Фильтры товаров')
        self.assertNotContains(response, '<body')
