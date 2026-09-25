from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from main_product_manager.models import MainProduct
from product_pricing.models import ProductPrice, ProductPriceRule, ProductPriceType
from product_pricing.services import calculate_product_prices, product_price_rows
from supplier_manager.models import Supplier

from product.filters import matching_product_pks
from product.models import Brand, Category, Product


class DetailTestCase(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username='u', password='pw'))
        self.supplier = Supplier.objects.create(name='Склад', price_priority=1)
        self.product = Product.objects.create(number='SKU-1', name='Смеситель')
        self.other = Product.objects.create(number='SKU-2', name='Кран')
        self.row = MainProduct.objects.create(product=self.product, supplier=self.supplier, article='A1',
                                              sku='SKU-1', name='Смеситель у поставщика',
                                              prime_cost=Decimal('100'), stock=3)

    def hx_post(self, url, data=None):
        return self.client.post(url, data or {}, HTTP_HX_REQUEST='true')


class ProductDetailPageTests(DetailTestCase):
    def test_page_shows_product_prices_and_main_product_rows(self):
        retail = ProductPriceType.objects.create(name='Розничная')
        general = ProductPriceRule.objects.create(name='Общая', price_type=retail, markup=Decimal('50'))
        special = ProductPriceRule.objects.create(name='Особая', price_type=retail, markup=Decimal('10'),
                                                  priority=10)
        special.products.add(self.product)
        self.product.prime_cost = Decimal('100')
        self.product.save()
        calculate_product_prices()

        response = self.client.get(reverse('product-detail', kwargs={'pk': self.product.pk}))

        self.assertContains(response, 'Смеситель у поставщика')
        self.assertContains(response, '110,00')
        self.assertContains(response, 'Особая')
        self.assertContains(response, 'Перекрыты: Общая')
        self.assertContains(response, reverse('main-product-move', kwargs={'pk': self.row.pk}))

    def test_products_table_links_to_the_card(self):
        response = self.client.get(reverse('products'))
        self.assertContains(response, reverse('product-detail', kwargs={'pk': self.product.pk}))

    def test_price_rows_list_matching_rules_by_priority(self):
        retail = ProductPriceType.objects.create(name='Розничная')
        self.product.prime_cost = Decimal('100')
        self.product.save()
        low = ProductPriceRule.objects.create(name='Общая', price_type=retail, priority=100)
        high = ProductPriceRule.objects.create(name='Особая', price_type=retail, priority=1)
        ProductPriceRule.objects.create(name='Выключена', price_type=retail, is_active=False)

        rows = product_price_rows(self.product)

        self.assertEqual(rows[0]['rules'], [high, low])


class ProductEditTests(DetailTestCase):
    def test_product_without_pim_data_is_fully_editable_and_searchable(self):
        brand = Brand.objects.create(pim_id='b', name='Grohe')
        category = Category.objects.create(name='Смесители')

        response = self.hx_post(reverse('product-update', kwargs={'pk': self.product.pk}),
                                {'number': 'SKU-1', 'name': 'Смеситель для кухни',
                                 'brand': brand.pk, 'categories': [category.pk]})

        self.assertEqual(response.headers.get('HX-Refresh'), 'true')
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Смеситель для кухни')
        self.assertEqual(self.product.brand, brand)
        self.assertEqual(list(self.product.categories.all()), [category])
        self.assertIn(self.product.pk, list(
            Product.objects.filter(pk__in=matching_product_pks('кухни')).values_list('pk', flat=True)))

    def test_pim_fields_of_a_synced_product_are_read_only(self):
        self.product.raw_data = {'name': 'Смеситель'}
        self.product.save()

        self.hx_post(reverse('product-update', kwargs={'pk': self.product.pk}),
                     {'number': 'SKU-1-NEW', 'name': 'Другое название'})

        self.product.refresh_from_db()
        self.assertEqual(self.product.number, 'SKU-1-NEW')
        self.assertEqual(self.product.name, 'Смеситель')

    def test_number_is_unique_case_insensitively(self):
        response = self.hx_post(reverse('product-update', kwargs={'pk': self.product.pk}),
                                {'number': 'sku-2', 'name': 'Смеситель'})
        self.assertContains(response, 'Этот артикул уже у товара «Кран»')


class ProductDeleteTests(DetailTestCase):
    def test_product_with_main_product_rows_is_not_deleted(self):
        response = self.client.get(reverse('product-delete', kwargs={'pk': self.product.pk}))
        self.assertContains(response, 'Сначала перенесите их в другие товары')

        self.hx_post(reverse('product-delete', kwargs={'pk': self.product.pk}))
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_product_without_rows_is_deleted(self):
        response = self.hx_post(reverse('product-delete', kwargs={'pk': self.other.pk}))
        self.assertEqual(response.headers.get('HX-Redirect'), reverse('products'))
        self.assertFalse(Product.objects.filter(pk=self.other.pk).exists())


class RelinkTests(DetailTestCase):
    def test_attach_takes_the_row_from_its_product_and_recalculates_both(self):
        recalculated = Product.objects.get(pk=self.product.pk)
        self.hx_post(reverse('product-attach-main-product', kwargs={'pk': self.other.pk}),
                     {'main_product': self.row.pk})

        self.row.refresh_from_db()
        self.other.refresh_from_db()
        recalculated.refresh_from_db()
        self.assertEqual(self.row.product, self.other)
        self.assertEqual(self.other.prime_cost, Decimal('100'))
        self.assertIsNone(recalculated.prime_cost)

    def test_attach_search_finds_rows_of_other_products(self):
        response = self.client.get(reverse('product-attach-main-product', kwargs={'pk': self.other.pk}),
                                   {'q': 'A1'})
        self.assertContains(response, 'Смеситель у поставщика')
        self.assertContains(response, 'Привязать')

    def test_move_to_another_product(self):
        response = self.client.get(reverse('main-product-move', kwargs={'pk': self.row.pk}), {'q': 'SKU-2'})
        self.assertContains(response, 'Перенести сюда')
        self.assertNotContains(response, 'value="%s"' % self.product.pk)

        self.hx_post(reverse('main-product-move', kwargs={'pk': self.row.pk}), {'product': self.other.pk})

        self.row.refresh_from_db()
        self.assertEqual(self.row.product, self.other)


class ProductRuleTests(DetailTestCase):
    def setUp(self):
        super().setUp()
        self.retail = ProductPriceType.objects.create(name='Розничная')
        Product.objects.filter(pk__in=[self.product.pk, self.other.pk]).update(prime_cost=Decimal('100'))

    def test_rule_form_from_the_card_is_preset_to_the_product(self):
        response = self.client.get(reverse('product-price-rule-create'), {'product': self.product.pk})

        self.assertContains(response, 'name="products" value="%s"' % self.product.pk)
        self.assertContains(response, 'name="priority" value="10"')

    def test_product_rule_prices_only_its_products(self):
        response = self.hx_post(reverse('product-price-rule-create'), {
            'price_type': self.retail.pk, 'source': 'prime_cost', 'markup': '20', 'increase': '0',
            'priority': 10, 'is_active': 'on', 'products': [self.product.pk],
        })
        self.assertEqual(response.headers.get('HX-Refresh'), 'true')
        rule = ProductPriceRule.objects.get()
        self.assertEqual(rule.name, 'Розничная: Себестоимость + 20 % · SKU-1')

        calculate_product_prices()

        self.assertEqual(list(ProductPrice.objects.values_list('product_id', 'value')),
                         [(self.product.pk, Decimal('120.00'))])

    def test_preview_counts_only_the_chosen_products(self):
        response = self.client.post(reverse('product-price-rule-preview'), {
            'price_type': self.retail.pk, 'source': 'prime_cost', 'markup': '20', 'increase': '0',
            'priority': 10, 'is_active': 'on', 'products': [self.product.pk],
        })
        self.assertEqual(response.context['preview']['in_scope'], 1)
        self.assertContains(response, 'товары: SKU-1')
