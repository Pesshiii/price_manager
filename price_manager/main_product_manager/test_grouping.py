"""Тесты схлопывания MainProduct по общему pim_id на главной.

До этого у MainPage и MainProductTableView не было ни одного теста, поэтому
здесь же проверяется и то, что таблица вообще рендерится.

PIM-запросы замоканы во всех тестах: MainProductTableView.get_context_data
зовёт prefetch_pim_data, а тот при промахе кэша ходит в сеть — под настройками
prod с плейсхолдерными PIM_TOKEN/PIM_HOST это живой HTTP из теста.
"""

import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.postgres.search import SearchVector
from django.test import TestCase
from django.urls import reverse

from supplier_manager.models import Category, Currency, Supplier

from .columns import DEFAULT_VISIBLE_COLUMNS
from .grouping import NO_STOCK_DATA
from .models import MainProduct
from .utils import save_user_columns

TR_RE = re.compile(r'<tr\b[^>]*>', re.IGNORECASE)


@patch('main_product_manager.views.maybe_notify_pim_error', lambda *args, **kwargs: None)
@patch('main_product_manager.views.prefetch_pim_data', lambda records: {})
class GroupingTestCase(TestCase):
    """Общая обвязка: пользователь, категория, поставщики с приоритетами."""

    def setUp(self):
        self.user = User.objects.create_user('grouptester', password='pw')
        self.client.force_login(self.user)
        save_user_columns(self.user, list(DEFAULT_VISIBLE_COLUMNS))
        self.currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.category = Category.objects.create(name='Инструменты')

    def make_supplier(self, name, price_priority=None, stock_priority=None, **kwargs):
        return Supplier.objects.create(
            name=name,
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=kwargs.pop('delivery_days_available', 1),
            delivery_days_navailable=kwargs.pop('delivery_days_navailable', 7),
            price_priority=price_priority,
            stock_priority=stock_priority,
            **kwargs,
        )

    def make_product(self, article, category=None, **kwargs):
        product = MainProduct.objects.create(
            article=article,
            name=kwargs.pop('name', f'Товар {article}'),
            **kwargs,
        )
        if category is not None:
            product.categories.add(category)
        return product

    def index(self, term):
        """Заполнить search_vector по локальным полям, без похода в PIM."""
        MainProduct.objects.all().update(
            search_vector=SearchVector('name', 'article', config='russian')
        )
        return term

    def fetch(self, category=None, **params):
        if category is not None:
            url = reverse('mainproduct-table-bycat', kwargs={'category_pk': category.pk})
        else:
            url = reverse('mainproduct-table-nocat')
        response = self.client.get(url, params, headers={'hx-request': 'true'})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    # --- вспомогательные разборы отрендеренного html ---

    def head_rows(self, html):
        return [tag for tag in TR_RE.findall(html) if 'mp-group-head' in tag]

    def row_classes(self, html):
        """Открывающие теги строк <tbody> по порядку — для проверки соседства.

        Заголовок таблицы тоже <tr>, поэтому отрезаем всё до <tbody>.
        """
        body = html.split('<tbody', 1)[-1]
        return TR_RE.findall(body)

    def head_cells(self, html):
        """Ячейки первой строки-заголовка."""
        match = re.search(
            r'<tr\b[^>]*mp-group-head[^>]*>(.*?)</tr>', html, re.IGNORECASE | re.DOTALL
        )
        self.assertIsNotNone(match, 'строка-заголовок не найдена')
        return re.findall(r'<td\b[^>]*>(.*?)</td>', match.group(1), re.IGNORECASE | re.DOTALL)


class GroupFormationTests(GroupingTestCase):
    def test_shared_pim_id_collapses_into_one_head_row(self):
        supplier_a = self.make_supplier('A')
        supplier_b = self.make_supplier('B')
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier_a)
        self.make_product('B-1', self.category, pim_id='PIM-1', supplier=supplier_b)

        html = self.fetch(self.category)

        self.assertEqual(len(self.head_rows(html)), 1)
        # Группа из N членов даёт N+1 строку: заголовок плюс сами члены.
        self.assertEqual(html.count('mp-group-member'), 2)
        self.assertIn('mp-group-toggle', html)

    def test_head_shows_member_count(self):
        supplier_a = self.make_supplier('A')
        supplier_b = self.make_supplier('B')
        supplier_c = self.make_supplier('C')
        for index, supplier in enumerate((supplier_a, supplier_b, supplier_c)):
            self.make_product(f'X-{index}', self.category, pim_id='PIM-1', supplier=supplier)

        html = self.fetch(self.category)

        self.assertRegex(html, r'<span class="badge text-bg-light" title="Товаров в группе">\s*3\s*</span>')

    def test_lone_pim_id_stays_flat(self):
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=self.make_supplier('A'))

        html = self.fetch(self.category)

        self.assertEqual(self.head_rows(html), [])
        self.assertNotIn('mp-group-member', html)

    def test_null_and_blank_pim_id_never_group(self):
        """PARTITION BY по голому pim_id склеил бы их всех в одну фальшивую группу."""
        supplier = self.make_supplier('A')
        self.make_product('N-1', self.category, pim_id=None, supplier=supplier)
        self.make_product('N-2', self.category, pim_id=None, supplier=supplier)
        self.make_product('E-1', self.category, pim_id='', supplier=supplier)
        self.make_product('E-2', self.category, pim_id='', supplier=supplier)

        html = self.fetch(self.category)

        self.assertEqual(self.head_rows(html), [])
        self.assertNotIn('mp-group-member', html)

    def test_filter_breaking_a_pair_returns_it_to_a_flat_row(self):
        """Группа считается по отфильтрованному queryset, а не по всему каталогу."""
        supplier = self.make_supplier('A')
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier, stock=5)
        self.make_product('A-2', self.category, pim_id='PIM-1', supplier=supplier, stock=0)

        grouped = self.fetch(self.category)
        self.assertEqual(len(self.head_rows(grouped)), 1)

        # available=on выбивает второго члена — пары больше нет.
        filtered = self.fetch(self.category, available='on')
        self.assertEqual(self.head_rows(filtered), [])
        self.assertNotIn('mp-group-member', filtered)

    def test_members_in_different_categories_do_not_group(self):
        """Группа не пересекает таблицы: в каждой из них по одному члену."""
        other = Category.objects.create(name='Прочее')
        supplier = self.make_supplier('A')
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier)
        self.make_product('A-2', other, pim_id='PIM-1', supplier=supplier)

        self.assertEqual(self.head_rows(self.fetch(self.category)), [])
        self.assertEqual(self.head_rows(self.fetch(other)), [])

    def test_category_join_does_not_inflate_group_size(self):
        """Дедупликация до аннотирования: иначе Count(*) OVER посчитает дубли join."""
        child = Category.objects.create(name='Дрели', parent=self.category)
        supplier_a = self.make_supplier('A')
        supplier_b = self.make_supplier('B')
        for article, supplier in (('A-1', supplier_a), ('B-1', supplier_b)):
            product = self.make_product(article, self.category, pim_id='PIM-1', supplier=supplier)
            product.categories.add(child)

        html = self.fetch(self.category, categories=str(self.category.pk))

        self.assertRegex(html, r'title="Товаров в группе">\s*2\s*</span>')


class RepresentativeSelectionTests(GroupingTestCase):
    def test_unranked_suppliers_fall_back_to_smallest_id(self):
        """День первый: приоритеты никому не проставлены, побеждает наименьший id."""
        first = self.make_product(
            'A-1', self.category, pim_id='PIM-1', supplier=self.make_supplier('A'), prime_cost=100
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1', supplier=self.make_supplier('B'), prime_cost=200
        )

        cells = self.head_cells(self.fetch(self.category))

        self.assertLess(first.pk, MainProduct.objects.latest('id').pk)
        self.assertIn('100', ''.join(cells))
        self.assertNotIn('200', ''.join(cells))

    def test_price_priority_beats_id_order(self):
        self.make_product(
            'A-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('A', price_priority=5), prime_cost=100,
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('B', price_priority=1), prime_cost=200,
        )

        cells = ''.join(self.head_cells(self.fetch(self.category)))

        self.assertIn('200', cells)
        self.assertNotIn('100', cells)

    def test_price_selection_is_per_column_and_skips_nulls(self):
        """Два соседних ценовых значения законно приезжают от разных поставщиков."""
        save_user_columns(self.user, ['actions', 'prime_cost', 'wholesale_price'])
        self.make_product(
            'A-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('A', price_priority=1),
            prime_cost=100, wholesale_price=None,
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('B', price_priority=2),
            prime_cost=999, wholesale_price=250,
        )

        cells = ''.join(self.head_cells(self.fetch(self.category)))

        self.assertIn('100', cells)   # себестоимость — от приоритетного
        self.assertIn('250', cells)   # оптовая — сквозное падение на второго
        self.assertNotIn('999', cells)

    def test_supplier_product_columns_stay_empty_on_the_head(self):
        """Три Subquery-колонки в поколоночный проход не входят."""
        save_user_columns(self.user, [
            'actions', 'supplier_product_price', 'supplier_product_rrp',
            'supplier_product_discount_price',
        ])
        supplier_a = self.make_supplier('A', price_priority=1)
        supplier_b = self.make_supplier('B', price_priority=2)
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier_a)
        self.make_product('B-1', self.category, pim_id='PIM-1', supplier=supplier_b)

        cells = self.head_cells(self.fetch(self.category))

        # actions + три ценовые; ценовые обязаны быть прочерками.
        self.assertEqual([cell.strip() for cell in cells[1:]], ['—', '—', '—'])

    def test_other_columns_are_blank_on_the_head(self):
        save_user_columns(self.user, ['actions', 'sku', 'article', 'name', 'supplier'])
        self.make_product(
            'A-1', self.category, pim_id='PIM-1', sku='SKU-A',
            supplier=self.make_supplier('A', price_priority=1),
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1', sku='SKU-B',
            supplier=self.make_supplier('B', price_priority=2),
        )

        cells = ''.join(self.head_cells(self.fetch(self.category)))

        for own_value in ('SKU-A', 'SKU-B', 'A-1', 'B-1'):
            self.assertNotIn(own_value, cells)


class StockSelectionTests(GroupingTestCase):
    def test_stock_falls_through_nulls_by_stock_priority(self):
        self.make_product(
            'A-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('A', stock_priority=1), stock=None,
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('B', stock_priority=2, msg_available='Есть у B'),
            stock=7,
        )

        cells = ''.join(self.head_cells(self.fetch(self.category)))

        self.assertIn('7', cells)
        # Статус наличия — от того члена, чей остаток победил, а не от носителя.
        self.assertIn('Есть у B', cells)

    def test_null_stock_everywhere_shows_no_data_on_the_head(self):
        self.make_product(
            'A-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('A', stock_priority=1), stock=None,
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('B', stock_priority=2), stock=None,
        )

        cells = ''.join(self.head_cells(self.fetch(self.category)))

        self.assertIn(NO_STOCK_DATA, cells)
        self.assertEqual(NO_STOCK_DATA, 'Нет данных')

    def test_delivery_days_still_shown_when_nobody_reported_stock(self):
        self.make_product(
            'A-1', self.category, pim_id='PIM-1', stock=None,
            supplier=self.make_supplier(
                'A', stock_priority=1, delivery_days_available=2, delivery_days_navailable=42
            ),
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1', stock=None,
            supplier=self.make_supplier(
                'B', stock_priority=2, delivery_days_available=3, delivery_days_navailable=99
            ),
        )

        cells = ''.join(self.head_cells(self.fetch(self.category)))

        self.assertIn('42', cells)

    def test_member_row_with_null_stock_shows_no_data(self):
        """На строке-члене «Нет данных» — когда NULL у неё самой."""
        supplier = self.make_supplier('A', msg_navailable='Нет в наличии')
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier, stock=None)
        self.make_product('B-1', self.category, pim_id='PIM-1', supplier=supplier, stock=0)

        html = self.fetch(self.category)

        self.assertIn(NO_STOCK_DATA, html)
        # Нулевой остаток по-прежнему отдаёт сообщение поставщика, а не «Нет данных».
        self.assertIn('Нет в наличии', html)

    def test_flat_row_with_null_stock_shows_no_data(self):
        supplier = self.make_supplier('A')
        self.make_product('A-1', self.category, supplier=supplier, stock=None)

        self.assertIn(NO_STOCK_DATA, self.fetch(self.category))

    def test_row_without_supplier_and_null_stock_shows_no_data(self):
        """MainProduct.supplier nullable: «Нет данных» — про остаток, не про поставщика."""
        self.make_product('A-1', self.category, supplier=None, stock=None)

        self.assertIn(NO_STOCK_DATA, self.fetch(self.category))

    def test_row_without_supplier_but_known_stock_stays_blank(self):
        """Сообщение о наличии берётся у поставщика — без него его неоткуда взять."""
        self.make_product('A-1', self.category, supplier=None, stock=4)

        self.assertNotIn(NO_STOCK_DATA, self.fetch(self.category))


class GroupOrderingTests(GroupingTestCase):
    def test_members_are_adjacent_and_head_comes_first(self):
        supplier_a = self.make_supplier('A')
        supplier_b = self.make_supplier('B')
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier_a)
        self.make_product('Z-1', self.category, supplier=supplier_a)
        self.make_product('B-1', self.category, pim_id='PIM-1', supplier=supplier_b)

        rows = self.row_classes(self.fetch(self.category))
        kinds = [
            'head' if 'mp-group-head' in row else 'member' if 'mp-group-member' in row else 'flat'
            for row in rows
        ]

        self.assertEqual(kinds, ['head', 'member', 'member', 'flat'])

    def test_head_stays_first_on_descending_sort(self):
        """Нисходящая сортировка переворачивает весь кортёж order_by — хук её перехватывает."""
        supplier_a = self.make_supplier('A', price_priority=1)
        supplier_b = self.make_supplier('B', price_priority=2)
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier_a, prime_cost=10)
        self.make_product('B-1', self.category, pim_id='PIM-1', supplier=supplier_b, prime_cost=20)
        self.make_product('C-1', self.category, supplier=supplier_a, prime_cost=30)

        prefix = f'{self.category.pk}-'
        for direction in ('prime_cost', '-prime_cost'):
            with self.subTest(sort=direction):
                html = self.fetch(self.category, **{f'{prefix}sort': direction})
                kinds = [
                    'head' if 'mp-group-head' in row
                    else 'member' if 'mp-group-member' in row else 'flat'
                    for row in self.row_classes(html)
                ]
                self.assertEqual(kinds.index('head'), kinds.index('member') - 1)
                self.assertEqual(kinds.count('head'), 1)
                # Члены остаются соседними в обе стороны.
                self.assertEqual(kinds[kinds.index('head'):kinds.index('head') + 3],
                                 ['head', 'member', 'member'])

    def test_group_sits_at_position_of_its_smallest_id_member(self):
        supplier = self.make_supplier('A')
        first = self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier)
        self.make_product('M-1', self.category, supplier=supplier)
        self.make_product('B-1', self.category, pim_id='PIM-1', supplier=supplier)

        kinds = [
            'head' if 'mp-group-head' in row else 'member' if 'mp-group-member' in row else 'flat'
            for row in self.row_classes(self.fetch(self.category))
        ]

        # Группа встала на место первого товара, а не в хвост.
        self.assertEqual(kinds[0], 'head')
        self.assertEqual(first, MainProduct.objects.earliest('id'))


class GroupedSearchTests(GroupingTestCase):
    def test_grouping_survives_a_non_empty_search(self):
        """order_by('-rank') протекает в GROUP BY — на пустом поиске это не видно."""
        supplier_a = self.make_supplier('A')
        supplier_b = self.make_supplier('B')
        self.make_product(
            'A-1', self.category, pim_id='PIM-1', supplier=supplier_a, name='Дрель ударная'
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1', supplier=supplier_b, name='Дрель ударная'
        )
        self.make_product('C-1', self.category, supplier=supplier_a, name='Пила дисковая')
        self.index('Дрель')

        html = self.fetch(self.category, search='Дрель')

        self.assertEqual(len(self.head_rows(html)), 1)
        self.assertRegex(html, r'title="Товаров в группе">\s*2\s*</span>')
        kinds = [
            'head' if 'mp-group-head' in row else 'member' if 'mp-group-member' in row else 'flat'
            for row in self.row_classes(html)
        ]
        self.assertEqual(kinds[:3], ['head', 'member', 'member'])

    def test_search_does_not_inflate_group_size(self):
        supplier = self.make_supplier('A')
        self.make_product('A-1', self.category, pim_id='PIM-1', supplier=supplier, name='Дрель')
        self.make_product('B-1', self.category, pim_id='PIM-1', supplier=supplier, name='Дрель')
        self.index('Дрель')

        html = self.fetch(self.category, search='Дрель')

        self.assertRegex(html, r'title="Товаров в группе">\s*2\s*</span>')
