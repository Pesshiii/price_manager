"""Тесты выбора колонок MainProductTable.

Отдельно от test_grouping.py: там проверяется схлопывание по общему pim_id,
здесь — что выбранная пользователем колонка вообще доезжает до таблицы.
Обвязка нужна та же самая, поэтому GroupingTestCase импортируется как есть.

Декораторы @patch приходится повторять на каждом классе-наследнике, а не
ставить один раз на обвязку: как декоратор класса patch оборачивает только те
test_-методы, которые видны в момент декорирования. У GroupingTestCase своих
test_-методов нет, а методы наследников она уже не увидит — то есть @patch на
ней самой не защищает никого. Без этого MainProductTableView.get_context_data
зовёт prefetch_pim_data, а тот при промахе кэша ходит в сеть.
"""

import re
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .columns import AVAILABLE_COLUMN_MAP
from .models import MP_PRICES
from .tables import MainProductTable
from .test_grouping import GroupingTestCase
from .utils import save_user_columns


class PriceColumnDeclarationTests(TestCase):
    """Инвариант: каждая цена из MP_PRICES объявлена и в таблице, и в выборе колонок.

    kaspi_price приехал миграцией 0009 позже остальных шести цен: в models.py и
    columns.py его прописали, в MainProductTable.Meta.fields — забыли. Отказ был
    тихий, потому что MainProductTable.__init__ фильтрует выбор пользователя по
    AVAILABLE_COLUMN_MAP, куда kaspi_price входит: галочка сохранялась, колонка
    не рисовалась, исключения не было. Восьмая цена поедет ровно тем же путём,
    если эти два теста её не поймают.
    """

    def test_every_mp_price_is_a_table_column(self):
        missing = [price for price in MP_PRICES if price not in MainProductTable.base_columns]

        self.assertEqual(missing, [], 'цена есть в MP_PRICES, но не объявлена в MainProductTable')

    def test_every_mp_price_is_offered_in_the_column_picker(self):
        missing = [price for price in MP_PRICES if price not in AVAILABLE_COLUMN_MAP]

        self.assertEqual(missing, [], 'цена есть в MP_PRICES, но её нельзя выбрать в настройке колонок')


@patch('main_product_manager.views.maybe_notify_pim_error', lambda *args, **kwargs: None)
@patch('main_product_manager.views.prefetch_pim_data', lambda records: {})
class KaspiPriceColumnTests(GroupingTestCase):
    """«Цена Каспи», выбранная в настройке колонок, доходит до отрисовки.

    Колонка живая с обеих сторон: PriceManager предлагает kaspi_price и как
    source, и как dest, так что правило наценки может в неё писать — а показать
    результат на главной было нечем.
    """

    def fetch_response(self, category, **params):
        """То же, что GroupingTestCase.fetch, но отдаёт response — нужен context."""
        url = reverse('mainproduct-table-bycat', kwargs={'category_pk': category.pk})
        response = self.client.get(url, params, headers={'hx-request': 'true'})
        self.assertEqual(response.status_code, 200)
        return response

    def test_selected_kaspi_price_reaches_the_table_sequence(self):
        """Ровно то место, где колонка терялась.

        sequence собирается как [c for c in selected_columns if c in self.columns],
        а kaspi_price в self.columns не попадал — не будучи объявленным, он не
        отсеивался (скрывать было нечего) и не добавлялся.
        """
        save_user_columns(self.user, ['actions', 'kaspi_price'])
        self.make_product(
            'A-1', self.category, supplier=self.make_supplier('A'), kaspi_price=Decimal('7777')
        )

        table = self.fetch_response(self.category).context['table']

        self.assertIn('kaspi_price', list(table.sequence))
        self.assertIn('kaspi_price', [column.name for column in table.columns])

    def test_selected_kaspi_price_renders_its_value_on_a_flat_row(self):
        save_user_columns(self.user, ['actions', 'kaspi_price'])
        self.make_product(
            'A-1', self.category, supplier=self.make_supplier('A'), kaspi_price=Decimal('7777')
        )

        html = self.fetch(self.category)

        self.assertIn('Цена Каспи', html)
        self.assertIn('7777', html)

    def test_unselected_kaspi_price_stays_hidden(self):
        """Обратная сторона: объявление колонки не делает её видимой по умолчанию."""
        save_user_columns(self.user, ['actions', 'prime_cost'])
        self.make_product(
            'A-1', self.category, supplier=self.make_supplier('A'), kaspi_price=Decimal('7777')
        )

        html = self.fetch(self.category)

        self.assertNotIn('Цена Каспи', html)
        self.assertNotIn('7777', html)

    def test_kaspi_price_renders_on_a_group_head(self):
        """Оконная аннотация grp_kaspi_price до этой правки не считалась ни разу.

        kaspi_price давно лежит в GROUPED_PRICE_COLUMNS, но annotate_groups
        навешивает окно только на выбранные колонки — а выбрать её было нельзя.
        Меньшее значение price_priority выигрывает.
        """
        save_user_columns(self.user, ['actions', 'kaspi_price'])
        self.make_product(
            'A-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('A', price_priority=2), kaspi_price=Decimal('8888'),
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('B', price_priority=1), kaspi_price=Decimal('7777'),
        )

        cells = ''.join(self.head_cells(self.fetch(self.category)))

        self.assertIn('7777', cells)
        self.assertNotIn('8888', cells)

    def all_head_cells(self, html):
        """Ячейки всех строк-заголовков по порядку — head_cells отдаёт только первую."""
        rows = re.findall(
            r'<tr\b[^>]*mp-group-head[^>]*>(.*?)</tr>', html, re.IGNORECASE | re.DOTALL
        )
        self.assertNotEqual(rows, [], 'строк-заголовков не найдено')
        return [
            ''.join(re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.IGNORECASE | re.DOTALL))
            for row in rows
        ]

    def row_kinds(self, html):
        return [
            'head' if 'mp-group-head' in row
            else 'member' if 'mp-group-member' in row else 'flat'
            for row in self.row_classes(html)
        ]

    def test_kaspi_price_column_sorts_without_breaking_groups(self):
        """Клик по заголовку колонки — тоже впервые исполнимый путь.

        order_kaspi_price ставится на таблицу для каждого ключа
        AVAILABLE_COLUMN_MAP, но до этой правки колонки не было, так что
        _order_grouped и order_by_group на этом accessor не звались ни разу.
        Заголовок сортируется по своему значению и остаётся над своими членами
        в обе стороны.
        """
        save_user_columns(self.user, ['actions', 'kaspi_price'])
        first = self.make_supplier('Приоритетный', price_priority=1)
        second = self.make_supplier('Запасной', price_priority=2)
        self.make_product(
            'C-1', self.category, pim_id='PIM-CHEAP', supplier=first, kaspi_price=Decimal('100'),
        )
        self.make_product(
            'C-2', self.category, pim_id='PIM-CHEAP', supplier=second, kaspi_price=Decimal('150'),
        )
        self.make_product(
            'D-1', self.category, pim_id='PIM-DEAR', supplier=first, kaspi_price=Decimal('900'),
        )
        self.make_product(
            'D-2', self.category, pim_id='PIM-DEAR', supplier=second, kaspi_price=Decimal('950'),
        )
        prefix = f'{self.category.pk}-'

        ascending = self.fetch(self.category, **{f'{prefix}sort': 'kaspi_price'})
        descending = self.fetch(self.category, **{f'{prefix}sort': '-kaspi_price'})

        self.assertIn('100', self.all_head_cells(ascending)[0])
        self.assertIn('900', self.all_head_cells(descending)[0])
        # Обе группы целы в обе стороны: заголовок, затем ровно его два члена.
        for direction, html in (('kaspi_price', ascending), ('-kaspi_price', descending)):
            with self.subTest(sort=direction):
                self.assertEqual(
                    self.row_kinds(html),
                    ['head', 'member', 'member', 'head', 'member', 'member'],
                )

    def test_group_head_falls_through_to_the_next_member_for_kaspi_price(self):
        """Сквозной выбор по колонке: NULL у приоритетного не гасит всю группу."""
        save_user_columns(self.user, ['actions', 'kaspi_price'])
        self.make_product(
            'A-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('A', price_priority=1), kaspi_price=None,
        )
        self.make_product(
            'B-1', self.category, pim_id='PIM-1',
            supplier=self.make_supplier('B', price_priority=2), kaspi_price=Decimal('7777'),
        )

        cells = ''.join(self.head_cells(self.fetch(self.category)))

        self.assertIn('7777', cells)
