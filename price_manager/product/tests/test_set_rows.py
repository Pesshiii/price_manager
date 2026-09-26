from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from main_product_manager.models import MainProduct, MainProductLog
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

    def test_set_without_number_gets_no_row(self):
        self.kit.number = None
        self.kit.save(update_fields=['number'])

        self.assertEqual(sync_set_rows()['created'], 0)


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

        self.assertContains(response, 'Без поставщика')
        self.assertContains(response, '>набор</span>')
        self.assertContains(response, f'{reverse("mainproduct-create")}?product={self.kit.pk}')
