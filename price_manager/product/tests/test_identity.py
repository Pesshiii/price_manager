"""Товар — пара (артикул, бренд): откуда у товара бренд и как пара бережётся.

Шаг 3 перехода «товар = бренд + артикул» (.claude/shift-to-product-brief.md
§0.6). Бренд товара — бренд PIM, а без него — бренд, о котором поставщики
товара не спорят. Пара с брендом уникальна, без бренда — нет.
"""
from unittest import mock

from django.contrib.postgres.search import SearchQuery
from django.test import TestCase
from django.urls import reverse

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier
from supplier_product_manager.models import SupplierProduct

from product.forms import ProductForm
from product.models import Brand, BrandAlias, Product, brand_key
from product.services import brands as service
from product.services.pim_sync import apply_pim_product
from product.services.sets import _candidates, _pick


class _Fixture(TestCase):
    def setUp(self):
        self.bosch = Brand.objects.create(pim_id='br-bosch', name='Bosch')
        self.makita = Brand.objects.create(pim_id='br-makita', name='Makita')
        self.first = Supplier.objects.create(name='Первый')
        self.second = Supplier.objects.create(name='Второй')
        BrandAlias.objects.get_or_create(name_key=brand_key('Без бренда'),
                                         defaults={'name': 'Без бренда', 'brand': None})

    def row(self, product, supplier, brand_name=None, brand=None):
        """Строка ГП поставщика на товаре и её строка прайса с брендом."""
        article = f'A-{MainProduct.objects.count() + 1}'
        main_product = MainProduct.objects.create(product=product, supplier=supplier, article=article,
                                                  sku=product.number, name='Дрель')
        SupplierProduct.objects.create(supplier=supplier, main_product=main_product, article=article,
                                       name='Дрель', brand_name=brand_name, brand=brand)
        return main_product


class AdoptSupplierBrandsTests(_Fixture):
    def adopt(self):
        stats = service.adopt_supplier_brands()
        return stats

    def test_agreed_supplier_brand_becomes_the_products_brand(self):
        product = Product.objects.create(number='D-1', name='Дрель')
        self.row(product, self.first, 'BOSCH', self.bosch)
        self.row(product, self.second, 'Bosch', self.bosch)

        stats = self.adopt()

        product.refresh_from_db()
        self.assertEqual(product.brand, self.bosch)
        self.assertEqual(stats.adopted, 1)
        # Бренд дописан в поисковый вектор, без пересборки.
        self.assertTrue(Product.objects.filter(
            pk=product.pk, search_vector=SearchQuery('bosch', config='russian')).exists())

    def test_suppliers_naming_different_brands_leave_it_brandless(self):
        product = Product.objects.create(number='D-1')
        self.row(product, self.first, 'Bosch', self.bosch)
        self.row(product, self.second, 'Makita', self.makita)

        stats = self.adopt()

        product.refresh_from_db()
        self.assertIsNone(product.brand)
        self.assertEqual((stats.adopted, stats.disputed), (0, 1))

    def test_a_spelling_waiting_for_mapping_is_a_claim_too(self):
        product = Product.objects.create(number='D-1')
        self.row(product, self.first, 'Bosch', self.bosch)
        self.row(product, self.second, 'Бош-неизвестный')

        self.assertEqual(self.adopt().disputed, 1)
        product.refresh_from_db()
        self.assertIsNone(product.brand)

    def test_an_ignored_spelling_is_no_claim(self):
        product = Product.objects.create(number='D-1')
        self.row(product, self.first, 'Bosch', self.bosch)
        self.row(product, self.second, 'Без бренда')

        self.adopt()

        product.refresh_from_db()
        self.assertEqual(product.brand, self.bosch)

    def test_a_pair_held_by_another_product_is_not_taken(self):
        Product.objects.create(number='d-1', brand=self.bosch)
        product = Product.objects.create(number='D-1')
        self.row(product, self.first, 'Bosch', self.bosch)

        stats = self.adopt()

        product.refresh_from_db()
        self.assertIsNone(product.brand)
        self.assertEqual(stats.taken, 1)

    def test_of_brandless_twins_only_the_oldest_gets_the_pair(self):
        older = Product.objects.create(number='D-1')
        younger = Product.objects.create(number='d-1')
        self.row(older, self.first, 'Bosch', self.bosch)
        self.row(younger, self.second, 'Bosch', self.bosch)

        stats = self.adopt()

        older.refresh_from_db()
        younger.refresh_from_db()
        self.assertEqual((older.brand, younger.brand), (self.bosch, None))
        self.assertEqual((stats.adopted, stats.taken), (1, 1))

    def test_a_branded_product_is_left_alone(self):
        product = Product.objects.create(number='D-1', brand=self.makita)
        self.row(product, self.first, 'Bosch', self.bosch)

        self.assertEqual(self.adopt().adopted, 0)
        product.refresh_from_db()
        self.assertEqual(product.brand, self.makita)

    def test_resolution_dispatches_adoption_after_commit(self):
        with mock.patch('product.tasks.adopt_supplier_brands_task.delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            service.apply_brand_resolution(SupplierProduct.objects.all())

        delay.assert_called_once_with()


class InheritProductBrandsTests(_Fixture):
    """Строка прайса, о бренде которой поставщик молчит, берёт бренд своего товара.

    Бренд строки — половина пары (артикул, бренд): без него правка артикула
    увела бы строку на новый товар без бренда. Заявка поставщика сильнее,
    несведённое написание ждёт в окне «Бренды» без бренда.
    """

    def resolve(self):
        service.apply_brand_resolution(SupplierProduct.objects.all())

    def brand_of(self, main_product):
        return SupplierProduct.objects.get(main_product=main_product).brand

    def login(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user(username='brands', password='pw'))

    def test_a_row_without_a_claim_takes_its_products_brand(self):
        product = Product.objects.create(number='D-1', brand=self.bosch)
        silent = self.row(product, self.first)
        ignored = self.row(product, self.second, 'Без бренда')

        self.resolve()

        self.assertEqual((self.brand_of(silent), self.brand_of(ignored)), (self.bosch, self.bosch))

    def test_a_claim_wins_and_a_waiting_spelling_stays_in_the_queue(self):
        product = Product.objects.create(number='D-1', brand=self.bosch)
        claimed = self.row(product, self.first, 'Makita')
        waiting = self.row(product, self.second, 'Бош-неизвестный')

        self.resolve()

        self.assertEqual((self.brand_of(claimed), self.brand_of(waiting)), (self.makita, None))
        self.assertEqual([item.name for item in service.unmapped_names()], ['Бош-неизвестный'])

    def test_the_inherited_brand_follows_the_product(self):
        product = Product.objects.create(number='D-1', brand=self.bosch)
        row = self.row(product, self.first)
        loose = SupplierProduct.objects.create(supplier=self.first, article='LOOSE', name='Без строки ГП',
                                               brand=self.bosch)
        self.resolve()
        Product.objects.filter(pk=product.pk).update(brand=self.makita)

        self.resolve()

        loose.refresh_from_db()
        self.assertEqual((self.brand_of(row), loose.brand), (self.makita, None))

    def test_an_inherited_brand_is_no_vote(self):
        """Строку перенесли с товара Bosch на товар без бренда: прежний бренд ему не достаётся."""
        product = Product.objects.create(number='D-1')
        row = self.row(product, self.first, brand=self.bosch)

        self.assertEqual(service.adopt_supplier_brands().adopted, 0)

        product.refresh_from_db()
        self.assertIsNone(product.brand)
        self.assertIsNone(self.brand_of(row))

    def test_rows_of_an_adopted_product_take_its_brand(self):
        product = Product.objects.create(number='D-1')
        self.row(product, self.first, 'Bosch', self.bosch)
        silent = self.row(product, self.second)

        service.adopt_supplier_brands()

        self.assertEqual(self.brand_of(silent), self.bosch)

    def test_a_brand_from_pim_reaches_the_rows(self):
        product = Product.objects.create(number='D-1')
        row = self.row(product, self.first)

        apply_pim_product(product, {'id': 'p-1', 'brandId': 'br-makita', 'brandName': 'Makita'})

        self.assertEqual(self.brand_of(row), self.makita)

    def test_a_brand_set_on_the_card_reaches_the_rows(self):
        self.login()
        product = Product.objects.create(number='D-1', name='Дрель')
        row = self.row(product, self.first)

        self.client.post(reverse('product-update', args=[product.pk]),
                         {'number': 'D-1', 'name': 'Дрель', 'brand': self.bosch.pk}, HTTP_HX_REQUEST='true')

        self.assertEqual(self.brand_of(row), self.bosch)

    def test_a_moved_row_takes_its_new_products_brand(self):
        self.login()
        row = self.row(Product.objects.create(number='D-1', brand=self.bosch), self.first)
        target = Product.objects.create(number='D-2', brand=self.makita)
        self.resolve()

        self.client.post(reverse('main-product-move', args=[row.pk]), {'product': target.pk},
                         HTTP_HX_REQUEST='true')

        self.assertEqual(self.brand_of(row), self.makita)


class PimBrandTests(_Fixture):
    """apply_pim_product: PIM's brand wins only where it does not break identity."""

    def test_pim_without_a_brand_keeps_the_local_one(self):
        product = Product.objects.create(number='D-1', brand=self.bosch)

        apply_pim_product(product, {'id': 'p-1', 'name': 'Дрель'})

        self.assertEqual(Product.objects.get(pk=product.pk).brand, self.bosch)

    def test_a_brand_not_from_pim_is_kept_when_pim_disagrees(self):
        product = Product.objects.create(number='D-1', brand=self.bosch)

        with self.assertLogs('product.services.pim_sync', level='WARNING'):
            apply_pim_product(product, {'id': 'p-1', 'brandId': 'br-makita', 'brandName': 'Makita'})

        self.assertEqual(Product.objects.get(pk=product.pk).brand, self.bosch)

    def test_a_brand_pim_gave_follows_pim(self):
        product = Product.objects.create(number='D-1', brand=self.bosch,
                                         raw_data={'id': 'p-1', 'brandId': 'br-bosch'})

        apply_pim_product(product, {'id': 'p-1', 'brandId': 'br-makita', 'brandName': 'Makita'})

        self.assertEqual(Product.objects.get(pk=product.pk).brand, self.makita)

    def test_a_pair_held_by_another_product_is_not_set(self):
        Product.objects.create(number='d-1', brand=self.makita)
        product = Product.objects.create(number='D-1')

        with self.assertLogs('product.services.pim_sync', level='WARNING'):
            apply_pim_product(product, {'id': 'p-1', 'brandId': 'br-makita', 'brandName': 'Makita'})

        saved = Product.objects.get(pk=product.pk)
        self.assertIsNone(saved.brand)
        # Остальное из PIM записано: отказ — только в бренде.
        self.assertEqual(saved.raw_data['id'], 'p-1')


class ProductFormPairTests(_Fixture):
    def form(self, product, **data):
        payload = {'number': product.number, 'name': product.name or '', 'categories': []}
        payload.update(data)
        return ProductForm(payload, instance=product)

    def test_a_taken_pair_is_refused_with_a_link_to_its_product(self):
        holder = Product.objects.create(number='D-1', brand=self.bosch, name='Дрель Bosch')
        product = Product.objects.create(number='d-1')

        form = self.form(product, brand=self.bosch.pk)

        self.assertFalse(form.is_valid())
        error = form.errors['brand'][0]
        self.assertIn(f'href="/products/{holder.pk}/"', error)
        self.assertIn('Дрель Bosch', error)

    def test_brandless_products_may_share_a_number(self):
        Product.objects.create(number='D-1')
        product = Product.objects.create(number='OTHER')

        self.assertTrue(self.form(product, number='d-1').is_valid())


class SetCandidatesTests(_Fixture):
    """Наборы ищут наш товар по номеру, не беря товар другого бренда, чем у товара PIM."""

    def test_number_fallback_never_takes_a_contradicting_brand(self):
        bosch = Product.objects.create(number='KIT-1', brand=self.bosch)
        plain = Product.objects.create(number='kit-1')
        makita = Product.objects.create(number='KIT-1', brand=self.makita)

        self.assertEqual({p.pk for p in _candidates([], 'KIT-1', 'br-bosch')}, {bosch.pk, plain.pk})
        self.assertEqual({p.pk for p in _candidates([], 'KIT-1', None)}, {bosch.pk, plain.pk, makita.pk})

    def test_the_same_brand_is_preferred(self):
        Product.objects.create(number='kit-1')
        bosch = Product.objects.create(number='KIT-1', brand=self.bosch)

        self.assertEqual(_pick(_candidates([], 'KIT-1', 'br-bosch'), [], 'br-bosch').pk, bosch.pk)
