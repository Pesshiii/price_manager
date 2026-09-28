from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from main_product_manager.models import MainProduct
from product_price_manager.models import PriceTag
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
    def test_page_shows_fixed_pricetags_and_main_product_rows(self):
        PriceTag.objects.create(mp=self.row, dest='m_price', source='fixed_price', fixed_price=Decimal('12990'))

        response = self.client.get(reverse('product-detail', kwargs={'pk': self.product.pk}))

        self.assertContains(response, 'Смеситель у поставщика')
        self.assertContains(response, 'Фиксированные наценки')
        self.assertContains(response, '12')
        self.assertContains(response, reverse('pricetag-create', kwargs={'pk': self.row.pk}))
        self.assertContains(response, reverse('main-product-move', kwargs={'pk': self.row.pk}))

    def test_products_table_links_to_the_card(self):
        response = self.client.get(reverse('products'))
        self.assertContains(response, reverse('product-detail', kwargs={'pk': self.product.pk}))


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
    def test_attach_takes_the_row_from_its_product(self):
        self.hx_post(reverse('product-attach-main-product', kwargs={'pk': self.other.pk}),
                     {'main_product': self.row.pk})

        self.row.refresh_from_db()
        self.assertEqual(self.row.product, self.other)

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
