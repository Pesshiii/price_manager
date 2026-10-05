from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from main_product_manager.models import MainProduct, MainProductLog
from main_product_manager.utils import update_stocks
from supplier_manager.models import Supplier
from supplier_product_manager.models import SupplierProduct
from product_price_manager.models import PriceManager, PriceTag, update_prices

from product.services.set_rows import sync_set_rows
from product.tests.test_set_costs import SetFixture

# Из SetFixture: стойка — основная себестоимость 100 (уровень 1), полка — 40
# (у приоритетного 0, решает нижний уровень). Набор: 4 стойки + 2 полки.
KIT_COST = Decimal('480.00')


class SetRowSyncTests(SetFixture, TestCase):
    def setUp(self):
        self.make_sets()

    def set_row(self, product=None):
        return MainProduct.objects.get(product=product or self.kit, is_set=True)

    def test_every_set_gets_one_row_without_supplier_costing_its_components(self):
        stats = sync_set_rows()

        row = self.set_row()
        self.assertEqual(stats['created'], 1)
        self.assertIsNone(row.supplier_id)
        self.assertEqual((row.sku, row.article, row.name), ('KIT-1', 'KIT-1', 'Стеллаж'))
        self.assertEqual(row.prime_cost, KIT_COST)
        self.assertTrue(MainProductLog.objects.filter(main_product=row, price_type='prime_cost',
                                                      price=KIT_COST).exists())

    def test_second_run_creates_and_changes_nothing(self):
        sync_set_rows()

        self.assertEqual(sync_set_rows(), {'created': 0, 'retired': 0, 'updated': 0})
        self.assertEqual(MainProduct.objects.filter(is_set=True).count(), 1)

    def test_an_incomplete_set_has_no_cost_rather_than_a_partial_sum(self):
        self.add_missing_component()

        sync_set_rows()

        self.assertIsNone(self.set_row().prime_cost)

    def test_cost_follows_the_components(self):
        sync_set_rows()
        MainProduct.objects.filter(product=self.stand, supplier=self.first).update(prime_cost=Decimal('110'))

        self.assertEqual(sync_set_rows()['updated'], 1)
        self.assertEqual(self.set_row().prime_cost, Decimal('520.00'))

    def test_a_set_inside_a_set_settles_in_one_run(self):
        outer = self.kit.__class__.objects.create(number='BIG-1', name='Два стеллажа')
        self.item(self.kit, amount=2, set_product=outer)

        sync_set_rows()

        self.assertEqual(self.set_row(outer).prime_cost, KIT_COST * 2)

    def test_a_product_that_stopped_being_a_set_keeps_its_row_without_the_cost(self):
        sync_set_rows()
        self.kit.set_items.all().delete()

        self.assertEqual(sync_set_rows()['retired'], 1)
        row = MainProduct.objects.get(product=self.kit)
        self.assertEqual((row.is_set, row.prime_cost), (False, None))
        # Строка без поставщика бывает только у набора — бывшая уходит к
        # «Своему складу». Строки прайса у неё нет, и update_stocks её остаток
        # не трогает.
        self.assertEqual(row.supplier, Supplier.own_stock())
        self.assertFalse(SupplierProduct.objects.filter(main_product=row).exists())
        update_stocks()
        row.refresh_from_db()
        self.assertEqual(row.stock, 2)

    def test_a_stray_row_without_supplier_moves_to_own_stock_with_its_prices(self):
        stray = MainProduct.objects.create(product=self.stand, article='STRAY', name='Возврат', stock=3,
                                           prime_cost=Decimal('70'))

        self.assertEqual(sync_set_rows()['retired'], 1)

        stray.refresh_from_db()
        self.assertEqual((stray.supplier, stray.prime_cost, stray.stock),
                         (Supplier.own_stock(), Decimal('70'), 3))
        update_stocks()
        stray.refresh_from_db()
        self.assertEqual(stray.stock, 3)

    def with_delivery_days(self):
        for supplier, available, navailable in ((self.first, 1, 10), (self.second, 3, 30),
                                                (self.unranked, 7, 70)):
            supplier.delivery_days_available = available
            supplier.delivery_days_navailable = navailable
            supplier.save()

    def test_stock_is_how_many_sets_the_components_make_and_delivery_the_longest(self):
        self.with_delivery_days()

        sync_set_rows()

        row = self.set_row()
        # Стойка: основной остаток 9 у «Второго» (уровень 1 по остаткам) — 9 // 4 = 2.
        # Полка: 5 у «Без уровня» — 5 // 2 = 2. Срок — поставщиков этих остатков, при
        # наличии: 3 и 7, набору — 7.
        self.assertEqual((row.stock, row.set_delivery_days), (2, 7))
        self.assertEqual(row.get_delivery_days(), 7)
        self.assertTrue(MainProductLog.objects.filter(main_product=row, stock=2).exists())

    def test_without_stock_data_for_a_component_the_set_has_none(self):
        self.with_delivery_days()
        self.add_missing_component()

        sync_set_rows()

        row = self.set_row()
        self.assertEqual((row.stock, row.set_delivery_days), (None, None))

    def test_update_stocks_recounts_the_set_with_the_components(self):
        self.with_delivery_days()
        sync_set_rows()

        # Прайсы компонентов остатка не дали — update_stocks ставит им 0.
        for row in MainProduct.objects.filter(supplier__isnull=False):
            SupplierProduct.objects.create(supplier_id=row.supplier_id, main_product=row,
                                           article=row.article or row.sku, name=row.name or row.sku)
        update_stocks()

        row = self.set_row()
        # Нулевой остаток — нигде нет: срок «при отсутствии» у поставщика верхнего
        # уровня по остаткам — у стойки «Второй» (30), у полки «Первый» (10).
        self.assertEqual((row.stock, row.set_delivery_days), (0, 30))


class SetPricesAreLastTests(SetFixture, TestCase):
    """Наценки строки набора считают от свежей суммы комплектующих — в том же прогоне."""

    def setUp(self):
        self.make_sets()

    def test_unsupplied_rule_prices_the_set_from_the_new_cost_in_one_run(self):
        PriceManager.objects.create(name='Наборы +25%', supplier=None, source='prime_cost',
                                    dest='basic_price', markup=Decimal('25'))

        update_prices(logs=False)

        row = MainProduct.objects.get(product=self.kit, is_set=True)
        self.assertEqual(row.prime_cost, KIT_COST)
        self.assertEqual(row.basic_price, Decimal('600'))

    def test_manual_tag_on_the_set_row_follows_the_cost(self):
        sync_set_rows()
        row = MainProduct.objects.get(product=self.kit, is_set=True)
        PriceTag.objects.create(mp=row, source='prime_cost', dest='m_price', markup=Decimal('50'))
        MainProduct.objects.filter(product=self.stand, supplier=self.first).update(prime_cost=Decimal('110'))

        update_prices(logs=False)

        row.refresh_from_db()
        self.assertEqual(row.prime_cost, Decimal('520.00'))
        self.assertEqual(row.m_price, Decimal('780'))

    def test_unsupplied_rule_never_writes_the_set_prime_cost(self):
        PriceManager.objects.create(name='Себестоимость фикс', supplier=None, source='fixed_price',
                                    dest='prime_cost', fixed_price=Decimal('1'))

        update_prices(logs=False)

        self.assertEqual(MainProduct.objects.get(product=self.kit, is_set=True).prime_cost, KIT_COST)

    def test_supplier_rules_do_not_touch_rows_without_supplier(self):
        sync_set_rows()
        PriceManager.objects.create(name='Поставщик', supplier=self.first, source='prime_cost',
                                    dest='basic_price', markup=Decimal('10'))

        update_prices(logs=False)

        self.assertIsNone(MainProduct.objects.get(product=self.kit, is_set=True).basic_price)


class SetRowOnTheCardTests(SetFixture, TestCase):
    def setUp(self):
        self.make_sets()
        sync_set_rows()
        self.client.force_login(User.objects.create_user(username='card', password='pw'))

    def test_card_marks_the_set_row_and_offers_a_new_row(self):
        response = self.client.get(reverse('product-detail', kwargs={'pk': self.kit.pk}))

        self.assertContains(response, '>набор</span>')
        self.assertContains(response, f'{reverse("mainproduct-create")}?product={self.kit.pk}')
