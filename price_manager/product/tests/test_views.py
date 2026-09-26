import re
import textwrap
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from product.models import Brand, Category, Product
from product.tables import ProductTable


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

    def test_brand_and_categories_are_shown_under_the_name(self):
        """Отдельных колонок у них нет — они строкой под названием."""
        response = self.client.get(reverse('products'))

        self.assertContains(response, 'Grohe · Сантехника')

    def test_pagination_elides_the_middle_pages(self):
        Product.objects.bulk_create(
            Product(pim_id=f'pmp-bulk-{i}', number=f'BULK-{i}', name=f'Товар {i}')
            for i in range(200)
        )

        response = self.client.get(reverse('products'))

        self.assertEqual(response.context['table'].paginator.num_pages, 9)
        self.assertContains(response, '<span class="page-link">…</span>', html=True)
        self.assertContains(response, 'page=9')

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


class ProductCategoryGroupingTests(TestCase):
    """Выдача по категориям — порядок по умолчанию, с заголовком над группой."""

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)

        # Корни в дереве идут по имени (order_insertion_by): «Инструмент» раньше
        # «Крепежа», «Пилы» — внутри «Инструмента».
        self.tools = Category.objects.create(name='Инструмент')
        self.saws = Category.objects.create(name='Пилы', parent=self.tools)
        self.fasteners = Category.objects.create(name='Крепеж')

        self._product('F-2', 'Шуруп', self.fasteners)
        self._product('S-1', 'Пила', self.saws)
        self._product('F-1', 'Саморез', self.fasteners)
        self._product('L-1', 'Лампа')
        self._product('H-1', 'Молоток', self.tools)

    def _product(self, number, name, *categories):
        product = Product.objects.create(number=number, name=name)
        product.categories.add(*categories)
        return product

    def _rows(self, response):
        return [(header, row.record.number) for header, row in response.context['product_rows']]

    def test_products_are_ordered_by_category_with_a_header_over_each_group(self):
        response = self.client.get(reverse('products'))

        self.assertTrue(response.context['group_by_category'])
        self.assertEqual(self._rows(response), [
            (['Инструмент'], 'H-1'),
            (['Инструмент', 'Пилы'], 'S-1'),
            (['Крепеж'], 'F-1'),
            (None, 'F-2'),
            (['Без категории'], 'L-1'),
        ])

    def test_headers_render_as_rows_with_the_category_path(self):
        response = self.client.get(reverse('products'))

        self.assertContains(response, 'class="product-group-row"', count=4)
        self.assertContains(response, '<span>Пилы</span>', html=True)

    def test_htmx_fragment_carries_the_same_headers(self):
        response = self.client.get(reverse('products'), HTTP_HX_REQUEST='true')

        self.assertTemplateUsed(response, 'product/partials/table.html')
        self.assertContains(response, 'class="product-group-row"', count=4)

    def test_first_row_of_a_page_repeats_the_header_of_a_continuing_group(self):
        """Группа, начатая на прошлой странице, без заголовка читалась бы как
        продолжение чужой."""
        for i in range(30):
            self._product(f'F-BULK-{i:02}', f'Саморез {i:02}', self.fasteners)

        response = self.client.get(reverse('products'), {'page': 2})

        first_header, first_row = response.context['product_rows'][0]
        self.assertEqual(first_header, ['Крепеж'])
        self.assertIn(self.fasteners, first_row.record.categories.all())

    def test_column_sort_turns_grouping_off(self):
        response = self.client.get(reverse('products'), {'sort': 'number'})

        self.assertFalse(response.context['group_by_category'])
        self.assertEqual([header for header, _ in response.context['product_rows']], [None] * 5)
        self.assertNotContains(response, 'class="product-group-row"')
        self.assertEqual([number for _, number in self._rows(response)],
                         ['F-1', 'F-2', 'H-1', 'L-1', 'S-1'])

    def test_column_sort_offers_a_way_back_to_the_default_order(self):
        response = self.client.get(reverse('products'), {'sort': 'number'})

        self.assertContains(response, 'Сбросить сортировку')
        self.assertNotContains(self.client.get(reverse('products')), 'Сбросить сортировку')

    def test_search_keeps_grouping_and_puts_the_group_with_the_best_match_first(self):
        """Три порядка здесь дают три разных ответа, и тест различает их все:
        по релевантности вышло бы K-1, R-1, K-2 (группы вперемешку), по
        категориям в дереве — «Инструмент › Пилы» первой. Нужный — группа
        лучшего совпадения первой, внутри неё по релевантности, а товар,
        найденный только по номеру (rank NULL), — в конце."""
        def searchable(number, name, *categories):
            product = self._product(number, name, *categories)
            product.raw_data = {'name': name}
            product.save()
            product.rebuild_search_vector()

        searchable('R-1', 'Ручка молоток молоток', self.saws)
        searchable('K-2', 'Гвоздь молоток', self.fasteners)
        searchable('K-1', 'Молоток молоток молоток', self.fasteners)
        self._product('МОЛОТОК-9', 'Без данных PIM')

        response = self.client.get(reverse('products'), {'search': 'молоток'})

        self.assertTrue(response.context['group_by_category'])
        self.assertEqual(self._rows(response), [
            (['Крепеж'], 'K-1'),
            (None, 'K-2'),
            (['Инструмент', 'Пилы'], 'R-1'),
            (['Без категории'], 'МОЛОТОК-9'),
        ])

    def test_search_form_sends_the_filters_along(self):
        """Без hx-include поиск уносил только строку поиска: галочки в панели
        оставались, а выдача и адрес их уже не учитывали."""
        html = self.client.get(reverse('products')).content.decode()

        search_form = re.search(r'<form id="products-search-form".*?>', html, re.S).group(0)
        self.assertIn('hx-include="#product-filter"', search_form)

    def test_facet_filter_keeps_grouping(self):
        response = self.client.get(reverse('products'), {'categories': [self.tools.pk]})

        self.assertEqual(self._rows(response), [
            (['Инструмент'], 'H-1'),
            (['Инструмент', 'Пилы'], 'S-1'),
        ])

    def test_product_with_two_categories_is_listed_once_and_its_stock_is_not_doubled(self):
        """Ключ категории — агрегат по join на categories. Join размножает
        строки поставщиков на число категорий, и Sum по ним удвоил бы остаток —
        поэтому в этом режиме остаток считается подзапросом."""
        product = self._product('M-1', 'Набор', self.fasteners, self.saws)
        first, second = Supplier.objects.create(name='Первый'), Supplier.objects.create(name='Второй')
        MainProduct.objects.create(product=product, supplier=first, article='M1', name='Набор',
                                   stock=4, prime_cost=Decimal('10.00'))
        MainProduct.objects.create(product=product, supplier=second, article='M2', name='Набор',
                                   stock=6, prime_cost=Decimal('12.00'))

        response = self.client.get(reverse('products'))
        rows = [row for _, row in response.context['product_rows'] if row.record.number == 'M-1']

        self.assertEqual(len(rows), 1)
        record = rows[0].record
        self.assertEqual(record.total_stock, 10)
        self.assertEqual(record.supplier_count, 2)
        self.assertEqual(record.in_stock_count, 2)
        # Стоит под первой из своих категорий в порядке дерева — «Пилами»,
        # сразу за «Пилой», а не под «Крепежом».
        self.assertEqual(self._rows(response)[:3], [
            (['Инструмент'], 'H-1'),
            (['Инструмент', 'Пилы'], 'M-1'),
            (None, 'S-1'),
        ])


class ProductPhotoTests(TestCase):
    def test_photo_carries_a_large_size_for_hover_zoom(self):
        html = ProductTable([]).render_photo(Product(raw_data={'mainImageId': 'img-1'}))

        self.assertIn('src="/products/pim-image/img-1/medium/"', html)
        self.assertIn('data-zoom-src="/products/pim-image/img-1/large/"', html)
        self.assertIn('class="product-photo"', html)


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
        self.assertContains(response, 'Строк ГП нет')

    def test_filter_fragment_redirects_a_non_htmx_request(self):
        response = self.client.get(reverse('product-filter'))
        self.assertEqual(response.status_code, 302)

    def test_filter_fragment_renders_for_htmx(self):
        response = self.client.get(reverse('product-filter'), HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'product/partials/filter.html')

    def test_filter_fragment_does_not_leak_template_comments(self):
        """Многострочный {# #} Django комментарием не считает и отдаёт как текст.

        Так в дереве категорий у каждого листа печаталось пояснение
        разработчика. Корневой лист и вложенный — обе ветки шаблона.
        """
        root = Category.objects.create(name='Сантехника')
        # Пустые ветки панель скрывает — обоим листьям нужен товар.
        self.product.categories.add(
            Category.objects.create(name='Смесители', parent=root),
            Category.objects.create(name='Свет'),
        )

        response = self.client.get(reverse('product-filter'), HTTP_HX_REQUEST='true')

        self.assertContains(response, 'Смесители')
        self.assertContains(response, 'Свет')
        self.assertNotContains(response, '{#')
        self.assertNotContains(response, 'Отступ только у вложенного листа')

    def test_filter_panel_hides_empty_options_and_shows_counts(self):
        used = Brand.objects.create(pim_id='br-1', name='Используемый')
        Brand.objects.create(pim_id='br-2', name='Пустой')
        self.product.brand = used
        self.product.save()
        MainProduct.objects.create(product=self.product, supplier=self.supplier, article='A1')
        Supplier.objects.create(name='Без товаров')

        response = self.client.get(reverse('product-filter'), HTTP_HX_REQUEST='true')

        self.assertContains(response, 'Используемый')
        self.assertNotContains(response, 'Пустой')
        self.assertNotContains(response, 'Без товаров')
        self.assertContains(response, '<span class="facet-count">1</span>', count=2)

    def test_facets_fragment_redirects_a_non_htmx_request(self):
        response = self.client.get(reverse('product-facets'))
        self.assertEqual(response.status_code, 302)

    def test_facets_fragment_is_only_oob_lists(self):
        """Только списки и только OOB — панель целиком не перерисовывается.

        Иначе обновление фасетов сбросило бы поля цены и быстрый поиск
        посреди ввода, а обёртка без hx-swap-oob при hx-swap="none" просто
        потерялась бы.
        """
        MainProduct.objects.create(product=self.product, supplier=self.supplier, article='A1')

        response = self.client.get(reverse('product-facets'), HTTP_HX_REQUEST='true')
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<form', content)
        self.assertNotIn('price_from', content)
        self.assertIn('id="checkboxes_id_brand" hx-swap-oob="outerHTML"', content)
        self.assertIn('id="checkboxes_id_supplier" hx-swap-oob="outerHTML"', content)
        self.assertIn('id="div_id_categories" hx-swap-oob="true"', content)
        self.assertContains(response, 'Поставщик')

    def _facets_queries(self, branches, data=None):
        for i in range(branches):
            parent = Category.objects.create(name=f'Ветка {i}')
            self.product.categories.add(Category.objects.create(name=f'Лист {i}', parent=parent))
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reverse('product-facets'), data or {}, HTTP_HX_REQUEST='true')
        return len(queries)

    def test_facets_query_count_does_not_grow_with_the_tree(self):
        """Дерево перерисовывается после каждого фильтра — запрос на узел недопустим.

        Раскрытие ветки проверяло пересечение потомков с выбором запросом на
        каждый узел, даже когда ничего не выбрано.
        """
        small = self._facets_queries(2)
        large = self._facets_queries(20)
        self.assertEqual(small, large)

    def test_facets_query_count_with_a_selected_category(self):
        selected = Category.objects.create(name='Выбранная')
        self.product.categories.add(selected)
        small = self._facets_queries(2, {'categories': [selected.pk]})
        large = self._facets_queries(20, {'categories': [selected.pk]})
        self.assertEqual(small, large)

    def test_branch_with_a_selected_category_renders_expanded(self):
        root = Category.objects.create(name='Корень')
        other = Category.objects.create(name='Другая')
        leaf = Category.objects.create(name='Лист', parent=root)
        Category.objects.create(name='Лист другой', parent=other)
        self.product.categories.add(leaf, other.children.get())

        response = self.client.get(reverse('product-facets'), {'categories': [leaf.pk]},
                                   HTTP_HX_REQUEST='true')

        content = response.content.decode()
        self.assertEqual(content.count('aria-expanded="true"'), 1)
        self.assertIn(f'aria-controls="collapse-id_categories-{root.pk}', content)
        expanded = content.index('aria-expanded="true"')
        self.assertIn(f'collapse-id_categories-{root.pk}', content[expanded:expanded + 200])

    def test_table_response_signals_the_facets_to_refresh(self):
        response = self.client.get(reverse('products'), HTTP_HX_REQUEST='true')

        self.assertIn('products-updated', response.headers.get('HX-Trigger', ''))

    def test_page_listens_for_the_refresh_event(self):
        response = self.client.get(reverse('products'))

        self.assertContains(response, 'hx-get="%s"' % reverse('product-facets'))
        self.assertContains(response, 'hx-trigger="products-updated from:body"')

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

    def test_filter_panel_scripts_declare_nothing_at_top_level(self):
        """Второй чекбокс-фасет не должен повторно объявлять функцию.

        core/includes/checkbox_field.html подключается на каждый фасет (бренд и
        поставщик), и его <script> выполняется столько же раз. Верхнеуровневый
        const во второй раз падает в консоли с SyntaxError: Identifier has
        already been declared — поэтому всё объявляется внутри window-гарда.
        """
        response = self.client.get(reverse('product-filter'), HTTP_HX_REQUEST='true')
        content = response.content.decode()

        self.assertEqual(content.count('data-checkbox-filter>'), 2)
        scripts = [s for s in re.findall(r'<script[^>]*>(.*?)</script>', content, re.S)
                   if 'data-checkbox-filter' in s]
        self.assertEqual(len(scripts), 2)
        for script in scripts:
            top_level = re.findall(r'^(?:const|let|class)\s+\w+', textwrap.dedent(script), re.M)
            self.assertEqual(top_level, [], script)

    def test_htmx_fragment_carries_no_second_filter_panel(self):
        """Фрагмент не должен тащить с собой панель фильтров и шапку."""
        response = self.client.get(reverse('products'), HTTP_HX_REQUEST='true')

        self.assertNotContains(response, 'Фильтры товаров')
        self.assertNotContains(response, '<body')
