from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from main_product_manager.models import MainProduct
from product.models import Brand, Category, Product
from product.services.prices import recalculate_base_prices
from supplier_manager.models import Supplier

from .models import ProductPrice, ProductPriceRule, ProductPriceType
from .services import calculate_product_prices, push_prices_to_pim


class BasePricesTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(number='SKU-1')

    def add_row(self, supplier, **prices):
        return MainProduct.objects.create(product=self.product, supplier=supplier,
                                          article='A', name='x', **prices)

    def test_top_price_level_wins_and_takes_the_minimum_inside_it(self):
        first = Supplier.objects.create(name='A', price_priority=1)
        also_first = Supplier.objects.create(name='B', price_priority=1)
        second = Supplier.objects.create(name='C', price_priority=2)
        self.add_row(first, prime_cost=Decimal('120'))
        self.add_row(also_first, prime_cost=Decimal('110'))
        self.add_row(second, prime_cost=Decimal('50'))

        changed = recalculate_base_prices()

        self.product.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(self.product.prime_cost, Decimal('110'))
        self.assertIsNotNone(self.product.prices_updated_at)

    def test_zero_on_the_top_level_falls_through_to_the_next(self):
        self.add_row(Supplier.objects.create(name='A', price_priority=1), basic_price=Decimal('0'))
        self.add_row(Supplier.objects.create(name='B', price_priority=2), basic_price=Decimal('70'))

        recalculate_base_prices()

        self.product.refresh_from_db()
        self.assertEqual(self.product.basic_price, Decimal('70'))
        self.assertIsNone(self.product.m_price)

    def test_unchanged_prices_are_not_rewritten(self):
        self.add_row(Supplier.objects.create(name='A'), prime_cost=Decimal('10'))
        recalculate_base_prices()

        self.assertEqual(recalculate_base_prices(), 0)


class CalculatePricesTests(TestCase):
    def setUp(self):
        self.retail = ProductPriceType.objects.create(name='Розничная')
        self.root = Category.objects.create(name='Сантехника')
        self.child = Category.objects.create(name='Смесители', parent=self.root)
        self.brand = Brand.objects.create(pim_id='b1', name='Grohe')
        self.in_child = Product.objects.create(number='P1', prime_cost=Decimal('100'), brand=self.brand)
        self.in_child.categories.add(self.child)
        self.other = Product.objects.create(number='P2', prime_cost=Decimal('1000'))
        self.no_price = Product.objects.create(number='P3')

    def rule(self, **kwargs):
        kwargs.setdefault('name', 'Правило')
        kwargs.setdefault('price_type', self.retail)
        return ProductPriceRule.objects.create(**kwargs)

    def price(self, product, price_type=None):
        return ProductPrice.objects.filter(product=product, price_type=price_type or self.retail).first()

    def test_markup_increase_and_rounding(self):
        self.rule(markup=Decimal('25'), increase=Decimal('3'), rounding=Decimal('10'))

        calculate_product_prices()

        # 100 * 1.25 + 3 = 128 -> вверх до 10 = 130
        self.assertEqual(self.price(self.in_child).value, Decimal('130'))
        self.assertEqual(self.price(self.in_child).source_value, Decimal('100'))
        self.assertIsNone(self.price(self.no_price), 'без цены-источника цены нет')

    def test_category_matches_descendants(self):
        rule = self.rule(markup=Decimal('10'))
        rule.categories.add(self.root)

        calculate_product_prices()

        self.assertEqual(self.price(self.in_child).value, Decimal('110.00'))
        self.assertIsNone(self.price(self.other))

    def test_brand_and_price_range(self):
        self.rule(markup=Decimal('10'), price_from=Decimal('500')).brands.add(self.brand)
        calculate_product_prices()
        self.assertFalse(ProductPrice.objects.exists())

    def test_lower_priority_wins_and_rules_do_not_stack(self):
        self.rule(name='Общая', markup=Decimal('50'), priority=100)
        special = self.rule(name='Особая', markup=Decimal('10'), priority=1)

        calculate_product_prices()

        price = self.price(self.in_child)
        self.assertEqual(price.value, Decimal('110.00'))
        self.assertEqual(price.rule, special)
        self.assertEqual(self.price(self.other).value, Decimal('1100.00'))

    def test_fixed_price_ignores_source(self):
        self.rule(source='fixed_price', fixed_price=Decimal('999'))
        calculate_product_prices()
        self.assertEqual(self.price(self.no_price).value, Decimal('999'))

    def test_expired_or_disabled_rule_removes_its_prices(self):
        rule = self.rule(markup=Decimal('10'))
        calculate_product_prices()
        self.assertTrue(ProductPrice.objects.exists())

        rule.date_to = timezone.now() - timedelta(days=1)
        rule.save()
        calculate_product_prices()
        self.assertFalse(ProductPrice.objects.exists())

    def test_types_are_independent(self):
        wholesale = ProductPriceType.objects.create(name='Опт')
        self.rule(markup=Decimal('10'))
        self.rule(price_type=wholesale, markup=Decimal('5'))

        calculate_product_prices()

        self.assertEqual(self.price(self.in_child).value, Decimal('110.00'))
        self.assertEqual(self.price(self.in_child, wholesale).value, Decimal('105.00'))

    def test_second_run_without_changes_touches_nothing(self):
        self.rule(markup=Decimal('10'))
        calculate_product_prices()
        self.assertEqual(calculate_product_prices(), 0)


@override_settings(PIM_PRODUCT_PRICE_FIELDS={'prime_cost': 'pmPrimeCost'})
class PushPricesTests(TestCase):
    def setUp(self):
        self.retail = ProductPriceType.objects.create(name='Розничная', pim_field='pmRetail')
        self.product = Product.objects.create(number='P1', pim_id='pmp-1', prime_cost=Decimal('100'))
        ProductPrice.objects.create(product=self.product, price_type=self.retail, value=Decimal('150'))

    def test_pushes_changed_prices_and_remembers_them(self):
        with mock.patch('main_product_manager.utils._upsert_async',
                        return_value=[{'status': 'Updated', 'id': 'pmp-1'}]) as upsert, \
                mock.patch('time.sleep'):
            self.assertEqual(push_prices_to_pim([self.product.pk], delay=0), 1)
            payload = upsert.call_args.args[1][0]['payload']
            self.assertEqual(payload, {'id': 'pmp-1', 'platformID': str(self.product.pk), 'number': 'P1',
                                       'pmPrimeCost': 100.0, 'pmRetail': 150.0})

            # Второй раз — ничего не изменилось, в PIM не ходим.
            self.assertEqual(push_prices_to_pim([self.product.pk], delay=0), 0)
            self.assertEqual(upsert.call_count, 1)

    @override_settings(PIM_PRODUCT_PRICE_FIELDS={})
    def test_nothing_mapped_means_no_pim_calls(self):
        self.retail.pim_field = ''
        self.retail.save()
        with mock.patch('main_product_manager.utils._upsert_async') as upsert:
            self.assertEqual(push_prices_to_pim([self.product.pk]), 0)
        upsert.assert_not_called()

    def test_rejected_item_is_retried_next_time(self):
        from main_product_manager.utils import PimScanError

        with mock.patch('main_product_manager.utils._upsert_async', return_value=[{'status': 'Failed'}]), \
                mock.patch('main_product_manager.utils._record_pim_error'), mock.patch('time.sleep'):
            with self.assertRaises(PimScanError):
                push_prices_to_pim([self.product.pk], delay=0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.pim_pushed_prices, {})


class PagesTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username='u', password='pw'))
        self.retail = ProductPriceType.objects.create(name='Розничная')
        self.product = Product.objects.create(number='SKU-1', name='Смеситель', prime_cost=Decimal('100'))
        self.rule = ProductPriceRule.objects.create(name='Наценка 20%', price_type=self.retail,
                                                    markup=Decimal('20'))
        ProductPrice.objects.create(product=self.product, price_type=self.retail, value=Decimal('120'),
                                    source_value=Decimal('100'), rule=self.rule)

    def test_pricing_page_lists_types_and_rules(self):
        response = self.client.get(reverse('product-pricing'))
        self.assertContains(response, 'Розничная')
        self.assertContains(response, 'Наценка 20%')

    def test_rule_create_and_validation(self):
        url = reverse('product-price-rule-create')
        response = self.client.post(url, {'name': 'Фикс', 'price_type': self.retail.pk,
                                          'source': 'fixed_price', 'markup': 0, 'increase': 0,
                                          'priority': 100, 'is_active': 'on'}, HTTP_HX_REQUEST='true')
        self.assertContains(response, 'Укажите фиксированную цену')

        response = self.client.post(url, {'name': 'Фикс', 'price_type': self.retail.pk,
                                          'source': 'fixed_price', 'fixed_price': '500', 'markup': 0,
                                          'increase': 0, 'priority': 100, 'is_active': 'on'},
                                    HTTP_HX_REQUEST='true')
        self.assertEqual(response.headers.get('HX-Refresh'), 'true')
        self.assertTrue(ProductPriceRule.objects.filter(name='Фикс').exists())

    def test_type_with_rules_cannot_be_deleted(self):
        self.client.post(reverse('product-price-type-update', kwargs={'pk': self.retail.pk}),
                         {'delete': 'true'}, HTTP_HX_REQUEST='true')
        self.assertTrue(ProductPriceType.objects.filter(pk=self.retail.pk).exists())

    def test_products_page_shows_calculated_price_column(self):
        response = self.client.get(reverse('products'))
        self.assertContains(response, '<th class="text-end">Розничная</th>', html=True)
        self.assertContains(response, '120,00')
        self.assertContains(response, 'Наценка: Наценка 20%')

    def test_hidden_type_has_no_column(self):
        self.retail.show_on_page = False
        self.retail.save()
        response = self.client.get(reverse('products'))
        self.assertNotContains(response, 'Наценка: Наценка 20%')

    def test_suppliers_panel_shows_product_prices(self):
        response = self.client.get(reverse('product-suppliers', kwargs={'pk': self.product.pk}))
        self.assertContains(response, 'Расчётные:')
        self.assertContains(response, 'Себестоимость: 100')
