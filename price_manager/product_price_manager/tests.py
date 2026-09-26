from decimal import Decimal

from django.test import TestCase

from main_product_manager.models import MainProduct, MainProductLog
from supplier_manager.models import Currency, Discount, Supplier
from supplier_product_manager.models import SupplierProduct

from .models import PriceManager, PriceTag, clear_unsourced_prices, update_prices
from .views import PriceManagerCreate


class PriceManagerDiscountFilteringTests(TestCase):
    def setUp(self):
        self.currency, _ = Currency.objects.get_or_create(name='KZT', defaults={'value': Decimal('1')})
        self.supplier = Supplier.objects.create(
            name='Supplier A',
            currency=self.currency,
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

    def test_sp_source_uses_only_filtered_discount_group(self):
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

    def test_sp_source_without_discount_filter_admits_any_group(self):
        target_mp = self.create_main_product('MP-5', 'No discount limit MP')

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
            name='SP row',
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

    def test_pricetag_get_sprice_treats_null_source_as_fixed_price(self):
        mp = self.create_mp('M-FIX-NULL', 'Fixed source is null')
        pt = PriceTag.objects.create(
            mp=mp,
            source=None,
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
            fixed_price=Decimal('12990'),
        )

        self.assertEqual(pt.get_sprice(), Decimal('12990'))

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


    # A NULL or 0 source price is "no price". These three replace tests that
    # pinned the old behaviour — NULL read as 0, so the product was priced at the
    # rule's bare `increase` (or 0).

    def test_pricetag_sp_source_null_or_zero_is_no_price(self):
        mp = self.create_mp('M-NULL', 'NULL source')
        sp = SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='S-NULL-1',
            name='SP null',
            supplier_price=None,
        )
        pt = PriceTag.objects.create(
            mp=mp,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
        )

        self.assertIsNone(pt.get_sprice())
        self.assertIsNone(pt.get_dprice())
        sp.supplier_price = Decimal('0')
        sp.save()
        self.assertIsNone(pt.get_sprice())

    def test_pricemanager_apply_does_not_write_a_price_from_an_empty_source(self):
        mp = self.create_mp('M-ZERO', 'Zero price apply', basic_price=Decimal('999'))
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='S-ZERO-1',
            name='SP null',
            supplier_price=None,
        )
        manager = PriceManager.objects.create(
            name='PM-ZERO-FROM-NULL',
            supplier=self.supplier,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('500'),
        )

        self.assertEqual(manager.apply(), 0)
        mp.refresh_from_db()
        self.assertEqual(mp.basic_price, Decimal('999'))  # cleared by update_prices, not apply

    def test_pricetag_with_missing_source_does_not_change_the_product(self):
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

        self.assertIsNone(pt.get_mp())


class PriceManagerNameGenerationTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.create(name='EUR', value=Decimal('1'))
        self.supplier = Supplier.objects.create(
            name='Supplier Name',
            currency=self.currency,
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
        self.assertIn('РРЦ: Да', generated_name)
        self.assertIn('VIP', generated_name)
        self.assertIn('100', generated_name)
        self.assertIn('200', generated_name)
        self.assertIn('Расчет:', generated_name)


class UpdatePricesOrderingTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.create(name='USD', value=Decimal('2'))
        self.supplier = Supplier.objects.create(
            name='Supplier Ordering',
            currency=self.currency,
            delivery_days_available=1,
            delivery_days_navailable=2,
        )

    def test_update_prices_applies_fixed_after_supplier_markup(self):
        mp = MainProduct.objects.create(
            supplier=self.supplier,
            article='ORDER-1',
            name='Ordering target',
        )
        SupplierProduct.objects.create(
            main_product=mp,
            supplier=self.supplier,
            article='ORDER-SP-1',
            name='Ordering row',
            supplier_price=Decimal('100'),
        )
        PriceManager.objects.create(
            name='PM-MARKUP-FIRST',
            supplier=self.supplier,
            source='supplier_price',
            dest='basic_price',
            markup=Decimal('10'),
            increase=Decimal('0'),
        )
        PriceManager.objects.create(
            name='PM-FIXED-LAST',
            supplier=self.supplier,
            source='fixed_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
            fixed_price=Decimal('555'),
        )

        update_prices()
        mp.refresh_from_db()

        self.assertEqual(mp.basic_price, Decimal('555'))

    def test_update_prices_applies_fixed_pricetag_after_markup_pricetag(self):
        mp = MainProduct.objects.create(
            supplier=self.supplier,
            article='ORDER-2',
            name='Ordering by pricetag target',
        )
        PriceTag.objects.create(
            mp=mp,
            source='basic_price',
            dest='m_price',
            markup=Decimal('20'),
            increase=Decimal('5'),
            p_manager=None,
        )
        PriceTag.objects.create(
            mp=mp,
            source='fixed_price',
            dest='m_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
            fixed_price=Decimal('777'),
            p_manager=None,
        )
        mp.basic_price = Decimal('100')
        mp.save(update_fields=['basic_price'])

        update_prices()
        mp.refresh_from_db()

        self.assertEqual(mp.m_price, Decimal('777'))

    def test_update_prices_applies_all_fixed_price_types_for_same_product(self):
        mp = MainProduct.objects.create(
            supplier=self.supplier,
            article='ORDER-3',
            name='All fixed types target',
        )
        PriceTag.objects.create(
            mp=mp,
            source='fixed_price',
            dest='basic_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
            fixed_price=Decimal('300'),
            p_manager=None,
        )
        PriceTag.objects.create(
            mp=mp,
            source=None,
            dest='m_price',
            markup=Decimal('0'),
            increase=Decimal('0'),
            fixed_price=Decimal('450'),
            p_manager=None,
        )

        update_prices()
        mp.refresh_from_db()

        self.assertEqual(mp.basic_price, Decimal('300'))
        self.assertEqual(mp.m_price, Decimal('450'))


class ClearUnsourcedPricesTests(TestCase):
    """Цена ГП без источника (цена поставщика или ГП = NULL/0) очищается, а не
    становится надбавкой правила и не застывает старой."""

    def setUp(self):
        currency = Currency.objects.create(name='KZT-CLR', value=Decimal('1'))
        self.supplier = Supplier.objects.create(
            name='Supplier Clear', currency=currency,
            delivery_days_available=1, delivery_days_navailable=2,
        )

    def _product(self, supplier_price=None, rrp=None, **mp_prices):
        mp = MainProduct.objects.create(supplier=self.supplier, article=f'A-{MainProduct.objects.count()}',
                                        name='Товар', **mp_prices)
        sp = SupplierProduct.objects.create(main_product=mp, supplier=self.supplier, article=mp.article,
                                            name='Товар', supplier_price=supplier_price, rrp=rrp)
        return mp, sp

    def _rule(self, source, dest, **kwargs):
        return PriceManager.objects.create(
            name=f'R-{PriceManager.objects.count()}', supplier=self.supplier, source=source, dest=dest,
            markup=kwargs.pop('markup', Decimal('0')), increase=kwargs.pop('increase', Decimal('0')), **kwargs,
        )

    def _set_supplier_price(self, sp, value):
        sp.supplier_price = value
        sp.save()

    def test_rule_without_range_clears_instead_of_pricing_at_increase(self):
        mp, sp = self._product(supplier_price=Decimal('100'))
        self._rule('supplier_price', 'basic_price', increase=Decimal('500'))
        update_prices()
        mp.refresh_from_db()
        self.assertEqual(mp.basic_price, Decimal('600'))

        for empty in (None, Decimal('0')):
            with self.subTest(source=empty):
                self._set_supplier_price(sp, empty)
                update_prices()
                mp.refresh_from_db()
                self.assertIsNone(mp.basic_price)
                self._set_supplier_price(sp, Decimal('100'))
                update_prices()

    def test_ranged_rule_clears_a_product_that_left_the_range_with_its_price(self):
        mp, sp = self._product(supplier_price=Decimal('150'))
        self._rule('supplier_price', 'basic_price', price_from=Decimal('100'))
        update_prices()
        mp.refresh_from_db()
        self.assertEqual(mp.basic_price, Decimal('150'))

        self._set_supplier_price(sp, None)
        update_prices()

        mp.refresh_from_db()
        self.assertIsNone(mp.basic_price)
        self.assertTrue(MainProductLog.objects.filter(
            main_product=mp, price_type='basic_price', price__isnull=True).exists())

    def test_manual_pricetag_with_empty_source_clears(self):
        mp, _ = self._product(supplier_price=None, basic_price=Decimal('777'))
        PriceTag.objects.create(mp=mp, source='supplier_price', dest='basic_price', increase=Decimal('5'))

        update_prices()

        mp.refresh_from_db()
        self.assertIsNone(mp.basic_price)

    def test_cascade_clears_prices_derived_from_a_cleared_price(self):
        mp, sp = self._product(supplier_price=Decimal('100'))
        self._rule('supplier_price', 'basic_price')
        self._rule('basic_price', 'm_price', markup=Decimal('50'))
        update_prices()
        mp.refresh_from_db()
        self.assertEqual((mp.basic_price, mp.m_price), (Decimal('100'), Decimal('150')))

        self._set_supplier_price(sp, None)
        update_prices()

        mp.refresh_from_db()
        self.assertEqual((mp.basic_price, mp.m_price), (None, None))

    def test_fixed_price_tag_keeps_the_price(self):
        mp, _ = self._product(supplier_price=None)
        self._rule('supplier_price', 'basic_price', increase=Decimal('500'))
        PriceTag.objects.create(mp=mp, source=None, dest='basic_price', fixed_price=Decimal('700'))

        update_prices()

        mp.refresh_from_db()
        self.assertEqual(mp.basic_price, Decimal('700'))

    def test_another_rule_with_a_real_source_keeps_the_price(self):
        mp, _ = self._product(supplier_price=Decimal('100'), rrp=None)
        self._rule('rrp', 'basic_price')
        self._rule('supplier_price', 'basic_price')

        update_prices()

        mp.refresh_from_db()
        self.assertEqual(mp.basic_price, Decimal('100'))

    def test_product_without_a_rule_is_left_alone(self):
        mp, _ = self._product(supplier_price=None, basic_price=Decimal('321'))

        update_prices()

        mp.refresh_from_db()
        self.assertEqual(mp.basic_price, Decimal('321'))

    def test_clearing_is_idempotent(self):
        mp, sp = self._product(supplier_price=Decimal('100'))
        self._rule('supplier_price', 'basic_price')
        update_prices()
        self._set_supplier_price(sp, None)

        self.assertEqual(clear_unsourced_prices(), 1)
        logs = MainProductLog.objects.filter(main_product=mp).count()
        self.assertEqual(clear_unsourced_prices(), 0)
        update_prices()
        self.assertEqual(MainProductLog.objects.filter(main_product=mp).count(), logs)


class PriceTagListTests(TestCase):
    """Наценки в карточке ГП: заданные на товаре отдельно от пришедших из менеджеров."""

    def setUp(self):
        from django.contrib.auth.models import User
        currency, _ = Currency.objects.get_or_create(name='KZT', defaults={'value': Decimal('1')})
        self.supplier = Supplier.objects.create(name='Tags supplier', currency=currency,
                                                delivery_days_available=1, delivery_days_navailable=2)
        self.mp = MainProduct.objects.create(supplier=self.supplier, article='T-1', name='Tags row')
        self.client.force_login(User.objects.create_user(username='tags', password='pw'))

    def get_list(self):
        from django.urls import reverse
        return self.client.get(reverse('pricetag-list', kwargs={'pk': self.mp.pk}), HTTP_HX_REQUEST='true')

    def test_manual_and_manager_pricetags_are_split(self):
        from django.urls import reverse
        manual = PriceTag.objects.create(mp=self.mp, source='fixed_price', dest='m_price',
                                         fixed_price=Decimal('100'))
        pm = PriceManager.objects.create(name='Правило карточки', supplier=self.supplier,
                                         source='basic_price', dest='prime_cost',
                                         markup=Decimal('0'), increase=Decimal('0'))
        from_rule = PriceTag.objects.create(mp=self.mp, p_manager=pm, source='basic_price', dest='prime_cost')

        response = self.get_list()

        self.assertEqual(list(response.context['fixed_pricetags']), [manual])
        self.assertEqual(list(response.context['manager_pricetags']), [from_rule])
        content = response.content.decode()
        self.assertLess(content.index('Фиксированные'), content.index('Из менеджеров наценок'))
        self.assertLess(content.index('Из менеджеров наценок'), content.index('Правило карточки'))
        # Тег правила правится в менеджере: его перезапишет следующее применение.
        self.assertIn(reverse('pricetag-update', args=[manual.pk]), content)
        self.assertNotIn(reverse('pricetag-update', args=[from_rule.pk]), content)
        self.assertIn(reverse('pricemanager-update', args=[pm.pk]), content)

    def test_empty_sections_say_so(self):
        response = self.get_list()
        self.assertContains(response, 'Нет наценок, заданных для этого товара.')
        self.assertContains(response, 'Ни один менеджер наценок не применяется к этому товару.')



class UnsuppliedRuleTests(TestCase):
    """Наценка без поставщика — на строки ГП без поставщика, и только на них."""

    def setUp(self):
        currency, _ = Currency.objects.get_or_create(name='KZT', defaults={'value': Decimal('1')})
        self.supplier = Supplier.objects.create(name='Есть поставщик', currency=currency,
                                                delivery_days_available=1, delivery_days_navailable=2)
        self.loose = MainProduct.objects.create(article='R-1', name='Возврат', prime_cost=Decimal('100'))
        self.supplied = MainProduct.objects.create(supplier=self.supplier, article='S-1', name='Строка',
                                                   prime_cost=Decimal('100'))
        SupplierProduct.objects.create(supplier=self.supplier, main_product=self.supplied, article='S-1',
                                       name='Строка', supplier_price=Decimal('50'))

    def rule(self, **kwargs):
        defaults = dict(name='Без поставщика', supplier=None, source='prime_cost', dest='basic_price',
                        markup=Decimal('20'))
        defaults.update(kwargs)
        return PriceManager.objects.create(**defaults)

    def test_applies_to_rows_without_supplier_only(self):
        self.rule().apply(logs=False)

        self.loose.refresh_from_db()
        self.supplied.refresh_from_db()
        self.assertEqual(self.loose.basic_price, Decimal('120'))
        self.assertIsNone(self.supplied.basic_price)
        self.assertTrue(PriceTag.objects.filter(mp=self.loose, p_manager__name='Без поставщика').exists())

    def test_a_supplier_price_list_source_fits_nothing(self):
        rule = self.rule(source='supplier_price')

        self.assertEqual(rule.get_fitting_mps().count(), 0)

    def test_price_range_and_deletion_behave_like_a_supplier_rule(self):
        rule = self.rule(price_from=Decimal('150'))
        self.assertEqual(rule.get_fitting_mps().count(), 0)
        rule.price_from = None
        rule.save()
        rule.apply(logs=False)

        rule.delete()

        self.loose.refresh_from_db()
        self.assertIsNone(self.loose.basic_price)


class PriceManagerPageTests(TestCase):
    """«Наценки ГП»: все правила, фильтр по поставщику, создание без поставщика."""

    def setUp(self):
        from django.contrib.auth.models import User
        currency, _ = Currency.objects.get_or_create(name='KZT', defaults={'value': Decimal('1')})
        self.supplier = Supplier.objects.create(name='Поставщик страницы', currency=currency,
                                                delivery_days_available=1, delivery_days_navailable=2)
        PriceManager.objects.create(name='Правило поставщика', supplier=self.supplier, source='prime_cost',
                                    dest='basic_price')
        PriceManager.objects.create(name='Правило без поставщика', supplier=None, source='prime_cost',
                                    dest='m_price')
        self.client.force_login(User.objects.create_user(username='rules', password='pw'))

    def test_lists_rules_of_suppliers_and_without_supplier(self):
        from django.urls import reverse
        response = self.client.get(reverse('price-manager'))

        self.assertEqual(len(response.context['rules']), 2)
        self.assertContains(response, 'Без поставщика')
        self.assertContains(response, 'Поставщик страницы')

    def test_filters_to_rules_without_supplier(self):
        from django.urls import reverse
        response = self.client.get(reverse('price-manager'), {'supplier': 'none'})

        self.assertEqual([rule.name for rule in response.context['rules']], ['Правило без поставщика'])

    def test_creates_a_rule_without_supplier_and_refuses_price_list_sources(self):
        from django.urls import reverse
        url = reverse('price-manager-create')
        form = {'dest': 'wholesale_price', 'source': 'prime_cost', 'markup': '10', 'increase': '0',
                'fixed_price': '0'}

        form_page = self.client.get(url, HTTP_HX_REQUEST='true')
        self.assertNotContains(form_page, 'value="supplier_price"')

        bad = self.client.post(url, {**form, 'source': 'supplier_price'}, HTTP_HX_REQUEST='true')
        self.assertContains(bad, 'нет прайса поставщика')

        self.client.post(url, form, HTTP_HX_REQUEST='true')
        rule = PriceManager.objects.get(dest='wholesale_price')
        self.assertIsNone(rule.supplier_id)
        self.assertTrue(rule.name.startswith('Без поставщика'))

    def test_manual_tag_on_a_row_without_supplier_cannot_use_the_price_list(self):
        from django.urls import reverse
        row = MainProduct.objects.create(article='L-1', name='Остаток')

        response = self.client.post(reverse('pricetag-create', kwargs={'pk': row.pk}), {
            'source': 'rrp', 'dest': 'basic_price', 'markup': '0', 'increase': '0'}, HTTP_HX_REQUEST='true')

        self.assertContains(response, 'нет прайса поставщика')
        self.assertFalse(PriceTag.objects.filter(mp=row).exists())


class LiveRuleFormTests(TestCase):
    """Форма наценки ГП: поставщик — поле формы, перерисовка по ?refresh=1."""

    def setUp(self):
        from django.contrib.auth.models import User
        usd, _ = Currency.objects.get_or_create(name='USD', defaults={'value': Decimal('500')})
        self.supplier = Supplier.objects.create(name='Живой поставщик', currency=usd,
                                                delivery_days_available=1, delivery_days_navailable=2)
        self.other = Supplier.objects.create(name='Другой поставщик', currency=usd,
                                             delivery_days_available=1, delivery_days_navailable=2)
        self.own_group = Discount.objects.create(name='Своя группа', supplier=self.supplier)
        self.foreign_group = Discount.objects.create(name='Чужая группа', supplier=self.other)
        self.client.force_login(User.objects.create_user(username='live', password='pw'))

    def url(self, name='price-manager-create', **kwargs):
        from django.urls import reverse
        return reverse(name, kwargs=kwargs or None)

    def form(self, **overrides):
        data = {'supplier': str(self.supplier.pk), 'dest': 'basic_price', 'source': 'prime_cost',
                'markup': '10', 'increase': '0', 'fixed_price': '0'}
        data.update(overrides)
        return data

    def test_refresh_redraws_for_the_chosen_supplier_and_saves_nothing(self):
        response = self.client.post(self.url() + '?refresh=1',
                                    self.form(source='supplier_price', discounts=[self.own_group.pk]),
                                    HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PriceManager.objects.exists())
        self.assertContains(response, 'Своя группа')
        self.assertNotContains(response, 'Чужая группа')
        self.assertEqual(response.context['selected_discount_ids'], [self.own_group.pk])
        # От цены из прайса диапазон — в валюте поставщика.
        self.assertContains(response, '>USD<')

    def test_refresh_without_supplier_drops_price_list_sources_and_dest(self):
        response = self.client.post(self.url() + '?refresh=1', self.form(supplier='', dest='m_price'),
                                    HTTP_HX_REQUEST='true')

        choices = [value for value, _ in response.context['form'].fields['source'].widget.choices]
        self.assertNotIn('supplier_price', choices)
        self.assertNotIn('rrp', choices)
        self.assertNotIn('m_price', choices)
        self.assertIn('prime_cost', choices)
        self.assertNotContains(response, 'Своя группа')

    def test_supplier_page_link_only_preselects(self):
        response = self.client.get(self.url('pricemanager-create', pk=self.supplier.pk), HTTP_HX_REQUEST='true')

        self.assertEqual(response.context['supplier'], self.supplier)
        self.assertContains(response, f'hx-post="{self.url()}"')

    def test_saves_under_the_supplier_chosen_in_the_form(self):
        self.client.post(self.url('pricemanager-create', pk=self.other.pk),
                         self.form(discounts=[self.own_group.pk]), HTTP_HX_REQUEST='true')

        rule = PriceManager.objects.get()
        self.assertEqual(rule.supplier, self.supplier)
        self.assertEqual(list(rule.discounts.all()), [self.own_group])

    def test_a_discount_group_of_another_supplier_is_refused(self):
        response = self.client.post(self.url(), self.form(discounts=[self.foreign_group.pk]),
                                    HTTP_HX_REQUEST='true')

        self.assertFalse(PriceManager.objects.exists())
        self.assertTrue(response.context['form'].errors.get('discounts'))

    def test_edit_refresh_saves_nothing_and_keeps_the_supplier(self):
        row = MainProduct.objects.create(supplier=self.supplier, article='E-1', name='Строка',
                                         prime_cost=Decimal('100'))
        SupplierProduct.objects.create(supplier=self.supplier, main_product=row, article='E-1', name='Строка')
        rule = PriceManager.objects.create(name='Правило', supplier=self.supplier, source='prime_cost',
                                           dest='basic_price', markup=Decimal('10'))
        tags = PriceTag.objects.count()

        response = self.client.post(self.url('pricemanager-update', pk=rule.pk) + '?refresh=1',
                                    self.form(supplier=str(self.other.pk), markup='50', delete='true'),
                                    HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['supplier'], self.supplier)
        self.assertTrue(PriceManager.objects.filter(pk=rule.pk).exists())
        rule.refresh_from_db()
        self.assertEqual(rule.markup, Decimal('10'))
        self.assertEqual(PriceTag.objects.count(), tags)

    def test_edit_ignores_a_posted_supplier(self):
        rule = PriceManager.objects.create(name='Правило', supplier=self.supplier, source='prime_cost',
                                           dest='basic_price')

        self.client.post(self.url('pricemanager-update', pk=rule.pk),
                         self.form(supplier=str(self.other.pk), markup='25'), HTTP_HX_REQUEST='true')

        rule.refresh_from_db()
        self.assertEqual(rule.supplier, self.supplier)
        self.assertEqual(rule.markup, Decimal('25'))
