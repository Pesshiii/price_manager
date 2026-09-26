from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from main_product_manager.models import MainProduct
from product.models import Brand, Category, Product, ProductSetItem
from product.services.prices import recalculate_base_prices
from supplier_manager.models import Supplier

from .models import ProductPrice, ProductPriceRule, ProductPriceType
from .services import calculate_product_prices, preview_rule


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

    def test_same_level_is_decided_by_prime_cost_and_prices_come_from_that_supplier(self):
        """Не минимум каждой цены по отдельности: цены — у поставщика с меньшей
        себестоимостью, как в экспорте."""
        dear = Supplier.objects.create(name='A', price_priority=1)
        cheap = Supplier.objects.create(name='B', price_priority=1)
        self.add_row(dear, prime_cost=Decimal('100'), m_price=Decimal('500'))
        self.add_row(cheap, prime_cost=Decimal('90'), m_price=Decimal('800'))

        recalculate_base_prices()

        self.product.refresh_from_db()
        self.assertEqual(self.product.prime_cost, Decimal('90'))
        self.assertEqual(self.product.m_price, Decimal('800'))

    def test_winner_without_a_price_falls_back_to_the_next_by_cost(self):
        level = Supplier.objects.create(name='A', price_priority=1)
        other = Supplier.objects.create(name='B', price_priority=1)
        self.add_row(level, prime_cost=Decimal('50'))
        self.add_row(other, prime_cost=Decimal('60'), basic_price=Decimal('75'))

        recalculate_base_prices()

        self.product.refresh_from_db()
        self.assertEqual(self.product.basic_price, Decimal('75'))

    def test_supplier_price_list_prices_are_converted_to_tenge(self):
        from supplier_manager.models import Currency
        from supplier_product_manager.models import SupplierProduct

        usd = Currency.objects.create(name='USD', value=Decimal('500'))
        supplier = Supplier.objects.create(name='A', price_priority=1, currency=usd)
        row = self.add_row(supplier, prime_cost=Decimal('5000'))
        SupplierProduct.objects.create(main_product=row, supplier=supplier, article='A', name='x',
                                       supplier_price=Decimal('10'), rrp=Decimal('12.5'))

        recalculate_base_prices()

        self.product.refresh_from_db()
        self.assertEqual(self.product.supplier_price, Decimal('5000'))
        self.assertEqual(self.product.rrp, Decimal('6250'))
        self.assertIsNone(self.product.supplier_discount_price)

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

    def test_only_sets(self):
        component = Product.objects.create(number='C1')
        ProductSetItem.objects.create(set_product=self.other, component=component,
                                      component_pim_product_id='pim-c1')
        self.rule(markup=Decimal('10'), only_sets=True)

        calculate_product_prices()

        self.assertEqual(list(ProductPrice.objects.values_list('product', flat=True)), [self.other.pk])

    def test_supplier_price_list_source(self):
        self.in_child.rrp = Decimal('200')
        self.in_child.save()
        self.rule(source='rrp', markup=Decimal('-10'))

        calculate_product_prices()

        self.assertEqual(self.price(self.in_child).value, Decimal('180.00'))
        self.assertEqual(ProductPrice.objects.count(), 1)


class PreviewTests(TestCase):
    def setUp(self):
        self.retail = ProductPriceType.objects.create(name='Розничная')
        self.cat = Category.objects.create(name='Смесители')
        self.a = Product.objects.create(number='A', name='А', prime_cost=Decimal('100'))
        self.b = Product.objects.create(number='B', name='Б', prime_cost=Decimal('200'))
        self.c = Product.objects.create(number='C', name='В')  # без себестоимости
        for product in (self.a, self.b, self.c):
            product.categories.add(self.cat)

    def test_funnel_of_an_unsaved_rule(self):
        special_only_b = ProductPriceRule.objects.create(name='Только B', price_type=self.retail,
                                                         markup=Decimal('1'), priority=1,
                                                         price_from=Decimal('150'))
        calculate_product_prices()  # у B — цена от «Только B»

        draft = ProductPriceRule(price_type=self.retail, markup=Decimal('10'), priority=100)
        preview = preview_rule(draft, categories=[self.cat], brand_ids=[])

        self.assertEqual(preview['in_scope'], 3)
        self.assertEqual(preview['no_source'], 1)
        self.assertEqual(preview['taken_by'], [(special_only_b, 1)])
        self.assertEqual(preview['effective'], 1)
        self.assertEqual(preview['appear'], 1)
        self.assertEqual(preview['examples'][0]['value'], Decimal('110.00'))

    def test_higher_priority_draft_displaces_an_existing_rule(self):
        general = ProductPriceRule.objects.create(name='Общая', price_type=self.retail, markup=Decimal('50'))
        calculate_product_prices()

        draft = ProductPriceRule(price_type=self.retail, markup=Decimal('10'), priority=1)
        preview = preview_rule(draft, categories=[], brand_ids=[])

        self.assertEqual(preview['effective'], 2)
        self.assertEqual(preview['change'], 2)
        self.assertEqual(preview['displaced'], [(general, 2)])


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

    def test_empty_name_is_generated(self):
        self.client.post(reverse('product-price-rule-create'),
                         {'price_type': self.retail.pk, 'source': 'prime_cost', 'markup': '35', 'increase': '0',
                          'priority': 100, 'is_active': 'on'}, HTTP_HX_REQUEST='true')
        self.assertTrue(ProductPriceRule.objects.filter(name='Розничная: Себестоимость + 35 %').exists())

    def test_rule_modal_renders_pickers(self):
        Category.objects.create(name='Смесители')
        Brand.objects.create(pim_id='b', name='Grohe')
        response = self.client.get(reverse('product-price-rule-update', kwargs={'pk': self.rule.pk}))
        self.assertContains(response, 'data-picker')
        self.assertContains(response, 'Смесители')
        self.assertContains(response, 'Grohe')
        self.assertContains(response, 'Прайс поставщика (ПП), в тенге')

    def test_preview_endpoint(self):
        response = self.client.post(reverse('product-price-rule-preview'),
                                    {'price_type': self.retail.pk, 'source': 'prime_cost', 'markup': '50',
                                     'increase': '0', 'priority': 1, 'is_active': 'on'})
        self.assertContains(response, 'Получат цену от этой наценки')
        self.assertContains(response, '150,00')
        self.assertContains(response, 'изменится у 1')

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
