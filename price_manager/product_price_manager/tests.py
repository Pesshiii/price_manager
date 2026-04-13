from decimal import Decimal

from django.test import TestCase

from main_product_manager.models import MainProduct
from supplier_manager.models import Currency, Discount, Supplier
from supplier_product_manager.models import SupplierProduct

from .models import PriceManager, PriceTag
from .views import PriceManagerCreate


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


class PriceTagAndPriceManagerRuntimeTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.create(name='USD', value=Decimal('2'))
        self.supplier = Supplier.objects.create(
            name='Supplier Runtime',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )

    def create_mp(self, article, name, **kwargs):
        return MainProduct.objects.create(
            supplier=self.supplier,
            article=article,
            name=name,
            **kwargs,
        )

    def test_pricetag_get_sprice_mp_source_uses_mainproduct_field(self):
        mp = self.create_mp('M-1', 'MP source', basic_price=Decimal('321'))
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='S-1',
            name='SP row',
            supplier_price=Decimal('50'),
        )
        pt = PriceTag.objects.create(
            mp=mp,
            source='basic_price',
            dest='m_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )

        self.assertEqual(pt.get_sprice(), Decimal('321'))

    def test_pricetag_get_sprice_sp_source_uses_supplierproduct_and_currency(self):
        mp = self.create_mp('M-2', 'SP source')
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='S-2',
            name='SP row 1',
            supplier_price=Decimal('10'),
        )
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='S-3',
            name='SP row 2',
            supplier_price=Decimal('15'),
        )
        pt = PriceTag.objects.create(
            mp=mp,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )

        self.assertEqual(pt.get_sprice(), Decimal('30'))

    def test_pricetag_get_aggfunc_callable(self):
        agg = PriceTag.get_aggfunc()
        self.assertEqual(agg([Decimal('1'), Decimal('3')]), Decimal('3'))

    def test_pricemanager_delete_nulls_dest_price(self):
        mp = self.create_mp('M-3', 'Delete PM')
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='S-4',
            name='SP row',
            supplier_price=Decimal('100'),
        )
        manager = PriceManager.objects.create(
            name='PM-DELETE',
            supplier=self.supplier,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )
        manager.apply()
        mp.refresh_from_db()
        self.assertEqual(mp.basic_price, Decimal('200'))

        manager.delete()
        mp.refresh_from_db()
        self.assertIsNone(mp.basic_price)

    def test_apply_updates_price_updated_at(self):
        mp = self.create_mp('M-4', 'Apply timestamp')
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='S-5',
            name='SP row',
            supplier_price=Decimal('100'),
        )
        manager = PriceManager.objects.create(
            name='PM-APPLY-TS',
            supplier=self.supplier,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )

        self.assertIsNone(mp.price_updated_at)
        manager.apply()
        mp.refresh_from_db()
        self.assertIsNotNone(mp.price_updated_at)
        self.assertEqual(mp.basic_price, Decimal('200'))

    def test_no_crash_when_source_price_missing(self):
        mp = self.create_mp('M-5', 'Missing source')
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='S-6',
            name='SP row without price',
            supplier_price=None,
        )
        pt = PriceTag.objects.create(
            mp=mp,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('10'),
            increase=Decimal('5'),
        )

        self.assertIsNone(pt.get_sprice())
        self.assertIsNone(pt.get_dprice())
        self.assertIsNone(pt.get_mp())


class PriceManagerNameGenerationTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.create(name='EUR', value=Decimal('1'))
        self.supplier = Supplier.objects.create(
            name='Supplier Name',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )
        self.discount = Discount.objects.create(name='VIP', supplier=self.supplier)

    def test_build_generated_name_includes_all_requested_parts(self):
        view = PriceManagerCreate()
        cleaned_data = {
            'price_fixed': False,
            'source': 'supplier_price',
            'dest': 'basic_price',
            'has_rrp': True,
            'discounts': Discount.objects.filter(pk=self.discount.pk),
            'price_from': Decimal('100'),
            'price_to': Decimal('200'),
        }

        generated_name = view._build_generated_name(self.supplier, cleaned_data)

        self.assertIn('Supplier Name', generated_name)
        self.assertIn('Базовая цена', generated_name)
        self.assertIn('Цена поставщика в валюте поставщика', generated_name)
        self.assertIn('РРЦ Да', generated_name)
        self.assertIn('VIP', generated_name)
        self.assertIn('100', generated_name)
        self.assertIn('200', generated_name)
        self.assertIn('Расчет:', generated_name)
