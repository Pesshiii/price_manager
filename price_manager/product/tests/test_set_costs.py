from decimal import Decimal

from django.contrib.auth.models import User
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from product.export import SET_TITLES, ProductExporter
from product.main_values import main_row
from product.models import Product, ProductSetItem
from product.set_costs import set_totals_for
from product.tests.test_export import as_dicts, read_sheets


class SetFixture:
    """Набор из двух компонентов и один компонент, которого нет в Price Manager.

    Поставщики: «Первый» — уровень 1 по цене и 2 по остаткам, «Второй» —
    наоборот, «Без уровня» — общий нижний уровень.
    """

    def make_sets(self):
        self.first = Supplier.objects.create(name='Первый', price_priority=1, stock_priority=2)
        self.second = Supplier.objects.create(name='Второй', price_priority=2, stock_priority=1)
        self.unranked = Supplier.objects.create(name='Без уровня')

        self.stand = Product.objects.create(number='ST-1', name='Стойка')
        self.shelf = Product.objects.create(number='SH-1', name='Полка')
        self.kit = Product.objects.create(number='KIT-1', name='Стеллаж')

        # Стойка: у приоритетного по цене дороже, но он выше уровнем — берём его.
        self.mp(self.stand, self.first, cost='100', stock=3)
        self.mp(self.stand, self.second, cost='60', stock=9)
        # Полка: у приоритетного цена 0 («нет цены») — решает уровень ниже.
        self.mp(self.shelf, self.first, cost='0', stock=None)
        self.mp(self.shelf, self.unranked, cost='40', stock=5)

        self.item(self.stand, amount=4, sorting=0)
        self.item(self.shelf, amount=2, sorting=10)

    def mp(self, product, supplier, cost, stock):
        return MainProduct.objects.create(
            product=product, supplier=supplier, article=f'{product.number}-{supplier.pk}',
            name=product.name, prime_cost=Decimal(cost), stock=stock)

    def item(self, component, amount, sorting=0, set_product=None):
        return ProductSetItem.objects.create(
            set_product=set_product or self.kit, component=component,
            component_pim_product_id=f'pim-{component.pk if component else sorting}',
            component_number=component.number if component else 'NOPE-1',
            component_name=component.name if component else 'Блокнот',
            amount=amount, sorting=sorting)

    def add_missing_component(self):
        return self.item(None, amount=1, sorting=20)


class MainRowTests(SetFixture, TestCase):
    def setUp(self):
        self.make_sets()

    def rows(self, product):
        return list(MainProduct.objects.filter(product=product).select_related('supplier'))

    def test_higher_price_level_wins_over_a_cheaper_lower_one(self):
        cost, row = main_row(self.rows(self.stand), 'prime_cost', 'price_priority', min)
        self.assertEqual(cost, Decimal('100'))
        self.assertEqual(row.supplier, self.first)

    def test_zero_at_the_top_level_falls_through(self):
        cost, row = main_row(self.rows(self.shelf), 'prime_cost', 'price_priority', min)
        self.assertEqual(cost, Decimal('40'))
        self.assertEqual(row.supplier, self.unranked)

    def test_stock_uses_its_own_levels_and_max(self):
        stock, row = main_row(self.rows(self.stand), 'stock', 'stock_priority', max)
        self.assertEqual((stock, row.supplier), (9, self.second))

    def test_only_zeros_is_zero_and_nothing_is_none(self):
        self.assertEqual(main_row([], 'stock', 'stock_priority', max), (None, None))
        rows = self.rows(self.shelf)
        for row in rows:
            row.stock = 0
        self.assertEqual(main_row(rows, 'stock', 'stock_priority', max), (0, None))

    def test_matches_the_main_value_of_the_export(self):
        """Одно правило на два места: основная себестоимость компонента в
        выгрузке — та же, что идёт в расчёт набора."""
        content, _ = ProductExporter(QueryDict(), ['prime_cost', 'stock']).build()
        by_number = {row['Артикул']: row for row in as_dicts(read_sheets(content)['Товары'])}
        for product in (self.stand, self.shelf):
            cost, _ = main_row(self.rows(product), 'prime_cost', 'price_priority', min)
            stock, _ = main_row(self.rows(product), 'stock', 'stock_priority', max)
            self.assertEqual(by_number[product.number]['Себестоимость (основная)'], cost)
            self.assertEqual(by_number[product.number]['Остаток (основной)'], stock)


class SetTotalsTests(SetFixture, TestCase):
    def setUp(self):
        self.make_sets()

    def totals(self):
        return set_totals_for([self.kit.pk, self.stand.pk])

    def test_only_sets_get_totals(self):
        self.assertEqual(list(self.totals()), [self.kit.pk])

    def test_cost_is_amount_times_main_cost_summed(self):
        totals = self.totals()[self.kit.pk]
        # 4 × 100 (стойка у «Первого») + 2 × 40 (полка у «Без уровня»).
        self.assertEqual(totals.cost, Decimal('480'))
        self.assertEqual(totals.missing_cost, 0)

    def test_buildable_is_the_scarcest_component(self):
        totals = self.totals()[self.kit.pk]
        # Стойка: 9 // 4 = 2, полка: 5 // 2 = 2 — обе ограничивают.
        self.assertEqual(totals.buildable, 2)
        self.assertEqual([line.limiting for line in totals.lines], [True, True])

        MainProduct.objects.filter(product=self.shelf, supplier=self.unranked).update(stock=20)
        totals = self.totals()[self.kit.pk]
        self.assertEqual(totals.buildable, 2)
        self.assertEqual([line.limiting for line in totals.lines], [True, False])

    def test_missing_component_is_counted_not_hidden(self):
        self.add_missing_component()
        totals = self.totals()[self.kit.pk]
        self.assertEqual(totals.count, 3)
        self.assertEqual(totals.cost, Decimal('480'))
        self.assertEqual(totals.missing_cost, 1)
        self.assertEqual(totals.missing_stock, 1)
        self.assertEqual(totals.buildable, 2)

    def test_two_queries_for_any_number_of_sets(self):
        other = Product.objects.create(number='KIT-2', name='Второй набор')
        self.item(self.stand, amount=1, set_product=other)
        with self.assertNumQueries(2):
            totals = set_totals_for([self.kit.pk, other.pk])
            [line.cost for set_totals in totals.values() for line in set_totals.lines]


class SetPageTests(SetFixture, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)
        self.make_sets()

    def page(self, query=''):
        return self.client.get(reverse('products') + query).content.decode()

    def test_set_row_has_badge_and_cost_hint(self):
        html = self.page('?search=KIT-1')
        self.assertIn('product-set-badge', html)
        self.assertIn('из компл.: <span class="text-nowrap">480,00</span>', html)
        self.assertNotIn('нет цены у', html)

    def test_incomplete_set_is_marked(self):
        self.add_missing_component()
        html = self.page('?search=KIT-1')
        self.assertIn('нет цены у 1 из 3', html)

    def test_component_links_to_its_sets(self):
        html = self.page('?search=ST-1')
        self.assertIn(f'?contains={self.stand.pk}', html)
        self.assertIn('в 1 наборе', html)

    def test_contains_filter_lists_sets_with_the_component(self):
        other = Product.objects.create(number='KIT-2', name='Без стойки')
        self.item(self.shelf, amount=1, set_product=other)
        html = self.page(f'?contains={self.stand.pk}')
        self.assertIn('KIT-1', html)
        self.assertNotIn('KIT-2', html)
        self.assertNotIn('>SH-1<', html)

    def test_is_set_filter(self):
        html = self.page('?is_set=on')
        self.assertIn('KIT-1', html)
        self.assertNotIn('>ST-1<', html)

    def test_expand_shows_assembly_row_and_composition(self):
        html = self.client.get(reverse('product-suppliers', kwargs={'pk': self.kit.pk})).content.decode()
        self.assertIn('Из комплектующих', html)
        self.assertIn('480,00', html)
        self.assertIn('Стойка', html)
        self.assertIn('Первый', html)
        # Своих строк у этого набора нет, но это не «ни один поставщик»: есть состав.
        self.assertNotIn('Ни один поставщик', html)

    def test_expand_of_assembled_set_keeps_its_own_rows(self):
        own = Supplier.objects.create(name='Склад')
        self.mp(self.kit, own, cost='450', stock=1)
        html = self.client.get(reverse('product-suppliers', kwargs={'pk': self.kit.pk})).content.decode()
        self.assertIn('Склад', html)
        self.assertIn('Из комплектующих', html)

    def test_missing_component_is_listed_in_the_composition(self):
        self.add_missing_component()
        html = self.client.get(reverse('product-suppliers', kwargs={'pk': self.kit.pk})).content.decode()
        self.assertIn('Блокнот', html)
        self.assertIn('нет в Price Manager', html)

    def test_plain_product_expand_is_unchanged(self):
        html = self.client.get(reverse('product-suppliers', kwargs={'pk': self.stand.pk})).content.decode()
        self.assertNotIn('Из комплектующих', html)


class SetExportTests(SetFixture, TestCase):
    def setUp(self):
        self.make_sets()

    def export(self, query=''):
        content, _ = ProductExporter(QueryDict(query), ['prime_cost']).build()
        return read_sheets(content)['Товары']

    def test_set_columns_appear_with_sets(self):
        self.add_missing_component()
        rows = self.export()
        self.assertEqual(rows[0][-2:], SET_TITLES)
        by_number = {row['Артикул']: row for row in as_dicts(rows)}
        self.assertEqual(by_number['KIT-1'][SET_TITLES[0]], 480)
        self.assertEqual(by_number['KIT-1'][SET_TITLES[1]], '1 из 3')
        self.assertIsNone(by_number['ST-1'][SET_TITLES[0]])

    def test_no_set_columns_without_sets(self):
        rows = self.export('search=ST-1')
        self.assertNotIn(SET_TITLES[0], rows[0])
