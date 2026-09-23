from decimal import Decimal
from io import BytesIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from product.columns import COLUMN_LABELS
from product.export import ProductExporter, main_value, ordered_product_pks, ranked_suppliers
from product.models import Brand, Category, Product, ProductExport


def read_rows(content):
    sheet = load_workbook(BytesIO(content), read_only=True).active
    return [list(row) for row in sheet.iter_rows(values_only=True)]


class MainValueTests(TestCase):
    def test_first_non_zero_wins(self):
        self.assertEqual(main_value([Decimal('0'), None, Decimal('7')]), Decimal('7'))

    def test_all_zero_or_empty_gives_zero(self):
        self.assertEqual(main_value([None, 0, None]), 0)

    def test_all_empty_gives_empty(self):
        self.assertIsNone(main_value([None, None]))

    def test_no_suppliers_gives_empty(self):
        self.assertIsNone(main_value([]))


class RankedSuppliersTests(TestCase):
    def test_lower_priority_first_unranked_and_no_supplier_last(self):
        unranked = Supplier.objects.create(name='А-без приоритета')
        second = Supplier.objects.create(name='Б', price_priority=2)
        first = Supplier.objects.create(name='В', price_priority=1)
        ranked = ranked_suppliers({unranked.pk, second.pk, first.pk, None}, 'price_priority')
        self.assertEqual([name for _, name in ranked], ['В', 'Б', 'А-без приоритета', 'Без поставщика'])


class ExportContentTests(TestCase):
    def setUp(self):
        # По цене первым идёт А, по остаткам — Б.
        self.a = Supplier.objects.create(name='А', price_priority=1, stock_priority=2)
        self.b = Supplier.objects.create(name='Б', price_priority=2, stock_priority=1)
        brand = Brand.objects.create(pim_id='br-1', name='Grohe')
        category = Category.objects.create(name='Сантехника')
        self.product = Product.objects.create(pim_id='p-1', number='SKU-1', name='Смеситель',
                                              brand=brand)
        self.product.categories.add(category)
        MainProduct.objects.create(
            product=self.product, supplier=self.a, article='A-1', name='Смеситель А',
            prime_cost=Decimal('0'), basic_price=Decimal('100'), m_price=None, stock=0)
        MainProduct.objects.create(
            product=self.product, supplier=self.b, article='B-1', name='Смеситель Б',
            prime_cost=Decimal('80'), basic_price=Decimal('120'), m_price=None, stock=None)

    def export(self, columns, query=''):
        content, count = ProductExporter(QueryDict(query), columns).build()
        return read_rows(content), count

    def test_prices_and_stock_per_supplier_plus_main(self):
        rows, count = self.export(['prime_cost', 'basic_price', 'm_price', 'stock'])
        header, row = rows
        self.assertEqual(count, 1)
        # 4 колонки товара + 3 цены × (основная + 2 поставщика) + остаток × (основной + 2).
        self.assertEqual(len(header), 4 + 3 * 3 + 3)
        values = dict(zip(header, row))
        self.assertEqual(values['Артикул'], 'SKU-1')
        self.assertEqual(values['Бренд'], 'Grohe')
        self.assertEqual(values['Категории'], 'Сантехника')
        # У А (приоритет 1) себестоимость 0 — основная берётся у Б.
        self.assertEqual(values['Себестоимость (основная)'], 80)
        self.assertEqual(values['Себестоимость • А'], 0)
        self.assertEqual(values['Себестоимость • Б'], 80)
        self.assertEqual(values['Базовая цена (основная)'], 100)
        # Цены ИМ нет ни у кого.
        self.assertIsNone(values['Цена ИМ (основная)'])
        # Остаток: у Б (приоритет 1) NULL, у А 0 — основной 0, а не пусто.
        self.assertEqual(values['Остаток (основной)'], 0)
        self.assertIsNone(values['Остаток • Б'])
        self.assertEqual(header.index('Остаток • Б') + 1, header.index('Остаток • А'))

    def test_other_supplier_columns_go_per_supplier_without_main(self):
        rows, _ = self.export(['article', 'supplier__msg_available', 'actions'])
        header, row = rows
        self.assertEqual(header[4:], ['Артикул поставщика • А', 'Артикул поставщика • Б',
                                      'Поставщик • Сообщение при наличии • А',
                                      'Поставщик • Сообщение при наличии • Б'])
        self.assertEqual(row[4:6], ['A-1', 'B-1'])

    def test_every_selectable_column_is_writable(self):
        """«Поставщик» — объект модели, даты — с таймзоной: openpyxl не пишет ни то, ни другое."""
        MainProduct.objects.update(price_updated_at=timezone.now())
        rows, _ = self.export(list(COLUMN_LABELS))
        values = dict(zip(*rows))
        self.assertEqual(values['Поставщик • А'], 'А')
        self.assertIsNotNone(values['Последнее обновление цены • А'])

    def test_several_rows_of_one_supplier_fall_through_too(self):
        MainProduct.objects.filter(supplier=self.b).delete()
        MainProduct.objects.create(product=self.product, supplier=self.a, article='A-2',
                                   name='Смеситель А2', m_price=Decimal('55'))
        rows, _ = self.export(['m_price', 'article'])
        values = dict(zip(*rows))
        self.assertEqual(values['Цена ИМ • А'], 55)
        self.assertEqual(values['Артикул поставщика • А'], 'A-1; A-2')

    def test_supplier_columns_only_for_suppliers_of_exported_products(self):
        other = Product.objects.create(pim_id='p-2', number='SKU-2', name='Ванна')
        c = Supplier.objects.create(name='В', price_priority=3)
        MainProduct.objects.create(product=other, supplier=c, article='C-1', name='Ванна')
        rows, count = self.export(['m_price'], query='search=SKU-1')
        self.assertEqual(count, 1)
        self.assertNotIn('Цена ИМ • В', rows[0])


class ExportOrderTests(TestCase):
    """Файл идёт в том же порядке, что и страница."""

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)
        supplier = Supplier.objects.create(name='Поставщик')
        root = Category.objects.create(name='Б-категория')
        other = Category.objects.create(name='А-категория')
        for index, (number, category, stock) in enumerate([
            ('N-3', root, 5), ('N-1', other, 1), ('N-2', root, 9), ('N-4', None, 3),
        ]):
            product = Product.objects.create(pim_id=f'p-{index}', number=number,
                                             name=f'Кран {number}', raw_data={'name': f'Кран {number}'})
            if category:
                product.categories.add(category)
            product.rebuild_search_vector()
            MainProduct.objects.create(product=product, supplier=supplier, article=number,
                                       name=f'Кран {number}', stock=stock)

    def assert_same_order(self, query):
        response = self.client.get(reverse('products') + '?' + query)
        page = [row.record.pk for _, row in response.context['product_rows']]
        self.assertEqual(ordered_product_pks(QueryDict(query)), page)

    def test_default_by_category(self):
        self.assert_same_order('')

    def test_sorted_by_column(self):
        self.assert_same_order('sort=number')
        self.assert_same_order('sort=-total_stock')

    def test_search(self):
        self.assert_same_order('search=Кран')
        self.assert_same_order('search=Кран&sort=-number')


class ExportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.client.force_login(self.user)

    def test_post_queues_task_with_page_query_without_page_number(self):
        with mock.patch('product.views.export_products_task.delay') as delay:
            response = self.client.post(reverse('product-export'),
                                        {'query': '?search=кран&sort=number&page=3'})
        self.assertEqual(response.status_code, 200)
        kwargs = delay.call_args.kwargs
        self.assertEqual(QueryDict(kwargs['query']).dict(), {'search': 'кран', 'sort': 'number'})
        self.assertEqual(kwargs['user_id'], self.user.pk)
        self.assertIn('stock', kwargs['columns'])

    def test_download_only_for_owner(self):
        export = ProductExport(user=self.user, rows_count=1)
        export.file.save('products-test.xlsx', ContentFile(b'data'), save=True)
        response = self.client.get(reverse('product-export-download', kwargs={'pk': export.pk}))
        self.assertEqual(response.status_code, 200)

        stranger = User.objects.create_user(username='other', password='pw')
        self.client.force_login(stranger)
        response = self.client.get(reverse('product-export-download', kwargs={'pk': export.pk}))
        self.assertEqual(response.status_code, 404)

    def test_task_notifies_with_download_link(self):
        from core.models import PersistentNotification
        from product.tasks import export_products_task

        Product.objects.create(pim_id='p-1', number='SKU-1', name='Смеситель')
        export_products_task(query='', columns=['stock'], user_id=self.user.pk)
        export = ProductExport.objects.get(user=self.user)
        self.assertEqual(export.rows_count, 1)
        notification = PersistentNotification.objects.get(user=self.user)
        self.assertEqual(notification.link,
                         reverse('product-export-download', kwargs={'pk': export.pk}))
