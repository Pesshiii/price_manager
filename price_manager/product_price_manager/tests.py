from decimal import Decimal

from django.test import TestCase

from main_product_manager.models import MainProduct
from supplier_manager.models import Currency, Discount, Supplier
from supplier_product_manager.models import SupplierProduct

from .models import PriceManager, PriceTag, update_prices


class PriceManagerDiscountFilteringTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.create(name='KZT', value=Decimal('1'))
        self.supplier = Supplier.objects.create(
            name='Supplier A',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )
        self.discount_a = Discount.objects.create(name='A', supplier=self.supplier)
        self.discount_b = Discount.objects.create(name='B', supplier=self.supplier)

    def create_main_product(self, article, name, **prices):
        return MainProduct.objects.create(
            supplier=self.supplier,
            article=article,
            name=name,
            **prices,
        )

    def test_sp_source_uses_only_filtered_discount_group_for_min_price(self):
        target_mp = self.create_main_product('MP-1', 'Target MP')
        excluded_mp = self.create_main_product('MP-2', 'Excluded MP')

        SupplierProduct.objects.create(
            main_product=target_mp,
            supplier=self.supplier,
            article='SP-1',
            name='Valid discount row',
            supplier_price=Decimal('100'),
            discount=self.discount_a,
        )
        SupplierProduct.objects.create(
            main_product=target_mp,
            supplier=self.supplier,
            article='SP-2',
            name='Wrong discount row with lower price',
            supplier_price=Decimal('10'),
            discount=self.discount_b,
        )
        SupplierProduct.objects.create(
            main_product=excluded_mp,
            supplier=self.supplier,
            article='SP-3',
            name='Only wrong discount',
            supplier_price=Decimal('20'),
            discount=self.discount_b,
        )

        manager = PriceManager.objects.create(
            name='PM-SP-DISCOUNT',
            supplier=self.supplier,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )
        manager.discounts.add(self.discount_a)

        fitting = manager.get_fitting_mps()
        self.assertEqual(fitting.count(), 1)
        self.assertEqual(fitting.first().pk, target_mp.pk)
        self.assertEqual(fitting.first().source_price, Decimal('100'))
        self.assertEqual(fitting.first().changed_price, Decimal('100'))

    def test_mp_source_respects_discounts_for_applicability(self):
        target_mp = self.create_main_product('MP-3', 'Allowed MP', basic_price=Decimal('100'))
        excluded_mp = self.create_main_product('MP-4', 'Blocked MP', basic_price=Decimal('100'))

        SupplierProduct.objects.create(
            main_product=target_mp,
            supplier=self.supplier,
            article='SP-4',
            name='Discount A row',
            supplier_price=Decimal('50'),
            discount=self.discount_a,
        )
        SupplierProduct.objects.create(
            main_product=excluded_mp,
            supplier=self.supplier,
            article='SP-5',
            name='Discount B row',
            supplier_price=Decimal('50'),
            discount=self.discount_b,
        )

        manager = PriceManager.objects.create(
            name='PM-MP-DISCOUNT',
            supplier=self.supplier,
            source='basic_price',
            dest='m_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
            price_from=Decimal('90'),
            price_to=Decimal('110'),
        )
        manager.discounts.add(self.discount_a)

        fitting_ids = set(manager.get_fitting_mps().values_list('id', flat=True))
        self.assertSetEqual(fitting_ids, {target_mp.id})

    def test_without_discounts_sp_source_keeps_original_behavior(self):
        target_mp = self.create_main_product('MP-5', 'No discount limit MP')

        SupplierProduct.objects.create(
            main_product=target_mp,
            supplier=self.supplier,
            article='SP-6',
            name='Price 100',
            supplier_price=Decimal('100'),
            discount=self.discount_a,
        )
        SupplierProduct.objects.create(
            main_product=target_mp,
            supplier=self.supplier,
            article='SP-7',
            name='Price 10',
            supplier_price=Decimal('10'),
            discount=self.discount_b,
        )

        manager = PriceManager.objects.create(
            name='PM-SP-NO-DISCOUNT',
            supplier=self.supplier,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )

        fitting = manager.get_fitting_mps()
        self.assertEqual(fitting.count(), 1)
        self.assertEqual(fitting.first().source_price, Decimal('10'))
        self.assertEqual(fitting.first().changed_price, Decimal('10'))


class FixedPricePriorityTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.create(name='KZT', value=Decimal('1'))
        self.supplier = Supplier.objects.create(
            name='Supplier Fixed',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )
        self.mp = MainProduct.objects.create(
            supplier=self.supplier,
            article='MP-FIX-1',
            name='Main product fixed',
        )
        SupplierProduct.objects.create(
            main_product=self.mp,
            supplier=self.supplier,
            article='SP-FIX-1',
            name='Supplier row',
            supplier_price=Decimal('100'),
        )

    def test_fixed_pricetag_has_priority_over_price_manager_result(self):
        PriceManager.objects.create(
            name='PM-CALC-1',
            supplier=self.supplier,
            source='supplier_price',
            dest='m_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )
        PriceTag.objects.create(
            mp=self.mp,
            source='fixed_price',
            dest='m_price',
            fixed_price=Decimal('150'),
            markup=Decimal('0'),
            increase=Decimal('0'),
        )

        update_prices()
        self.mp.refresh_from_db()
        self.assertEqual(self.mp.m_price, Decimal('150'))

    def test_fixed_price_manager_has_priority_over_calculated_manager(self):
        PriceManager.objects.create(
            name='PM-CALC-2',
            supplier=self.supplier,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )
        PriceManager.objects.create(
            name='PM-FIXED-2',
            supplier=self.supplier,
            source='fixed_price',
            dest='basic_price',
            fixed_price=Decimal('200'),
            markup=Decimal('0'),
            increase=Decimal('0'),
        )

        update_prices()
        self.mp.refresh_from_db()
        self.assertEqual(self.mp.basic_price, Decimal('200'))

    def test_multiple_fixed_tags_update_multiple_dest_fields_for_same_product(self):
        PriceTag.objects.create(
            mp=self.mp,
            source='fixed_price',
            dest='m_price',
            fixed_price=Decimal('150'),
            markup=Decimal('0'),
            increase=Decimal('0'),
        )
        PriceTag.objects.create(
            mp=self.mp,
            source='fixed_price',
            dest='basic_price',
            fixed_price=Decimal('250'),
            markup=Decimal('0'),
            increase=Decimal('0'),
        )

        update_prices()
        self.mp.refresh_from_db()
        self.assertEqual(self.mp.m_price, Decimal('150'))
        self.assertEqual(self.mp.basic_price, Decimal('250'))
