from unittest.mock import patch

from django.contrib.postgres.search import SearchQuery
from django.db import IntegrityError
from django.test import TestCase

from main_product_manager.models import MainProduct
from product.models import Brand, Category, Product


class CategoryModelTests(TestCase):
    def test_slug_auto_generated_and_unique(self):
        # slugify(..., allow_unicode=True) lowercases without transliterating.
        root = Category.objects.create(name='Электроника')
        self.assertEqual(root.slug, 'электроника')

        dup = Category.objects.create(parent=root, name='Электроника')
        self.assertEqual(dup.slug, 'электроника-2')

    def test_str_includes_parent_path(self):
        root = Category.objects.create(name='Электроника')
        child = Category.objects.create(parent=root, name='Телефоны')
        self.assertEqual(str(root), 'Электроника')
        self.assertEqual(str(child), 'Электроника>Телефоны')

    def test_mptt_ancestors(self):
        root = Category.objects.create(name='A')
        mid = Category.objects.create(parent=root, name='B')
        leaf = Category.objects.create(parent=mid, name='C')
        self.assertEqual(
            [c.name for c in leaf.get_ancestors(include_self=True)],
            ['A', 'B', 'C'],
        )

    def test_pim_id_unique(self):
        Category.objects.create(name='A', pim_id='pim-1')
        with self.assertRaises(IntegrityError):
            Category.objects.create(name='B', pim_id='pim-1')

    def test_parent_name_unique_together(self):
        root = Category.objects.create(name='A')
        Category.objects.create(parent=root, name='B')
        with self.assertRaises(IntegrityError):
            Category.objects.create(parent=root, name='B')


class ProductModelTests(TestCase):
    def test_str(self):
        product = Product.objects.create(pim_id='p1', number='N1', name='Товар')
        self.assertEqual(str(product), 'N1 — Товар')

    def test_pim_id_unique(self):
        Product.objects.create(pim_id='p1', number='N1', name='A')
        with self.assertRaises(IntegrityError):
            Product.objects.create(pim_id='p1', number='N2', name='B')

    def test_number_unique(self):
        Product.objects.create(pim_id='p1', number='N1', name='A')
        with self.assertRaises(IntegrityError):
            Product.objects.create(pim_id='p2', number='N1', name='B')

    def test_name_is_not_unique(self):
        # Several local Products can sit on one PIM Product, and PIM does not
        # keep Product.name unique either.
        Product.objects.create(pim_id='p1', number='N1', name='A')
        Product.objects.create(pim_id='p2', number='N2', name='A')
        self.assertEqual(Product.objects.filter(name='A').count(), 2)

    def test_products_without_pim_id_coexist(self):
        # pim_id stays NULL until reindex pushes the PriceManagerProduct.
        Product.objects.create(pim_id=None, number='N1')
        Product.objects.create(pim_id=None, number='N2')
        self.assertEqual(Product.objects.filter(pim_id__isnull=True).count(), 2)

    def test_products_without_name_coexist(self):
        # Postgres treats NULLs as distinct in a unique index but '' as equal,
        # so a nameless product must store NULL. pim_sync used to coerce to ''
        # here, which made the second one fail to save.
        Product.objects.create(pim_id='p1', number='N1', name=None)
        Product.objects.create(pim_id='p2', number='N2', name=None)
        self.assertEqual(Product.objects.filter(name__isnull=True).count(), 2)

    def test_products_without_number_coexist(self):
        Product.objects.create(pim_id='p1', number=None, name='A')
        Product.objects.create(pim_id='p2', number=None, name='B')
        self.assertEqual(Product.objects.filter(number__isnull=True).count(), 2)


class BrandModelTests(TestCase):
    def test_pim_id_is_unique(self):
        Brand.objects.create(pim_id='b1', name='Bosch')
        with self.assertRaises(IntegrityError):
            Brand.objects.create(pim_id='b1', name='Bosch (другое написание)')

    def test_str_is_the_name(self):
        self.assertEqual(str(Brand.objects.create(pim_id='b2', name='Grohe')), 'Grohe')


class ProductSearchVectorTests(TestCase):
    """search_vector строится из raw_data и НИКОГДА не ходит в PIM.

    Сетевой вызов внутри метода модели — ровно то, чем болел
    MainProduct._build_searchvector(); проверяем, что здесь его нет.
    """

    RAW = {
        'name': 'Смеситель для кухни',
        'categoriesNames': {'c1': 'Сантехника', 'c2': 'Смесители'},
        'tag': ['кухня', 'хром'],
        'brandName': 'Grohe',
        'description': 'Однорычажный смеситель',
        'longDescription': 'Подробное описание товара',
    }

    def test_vector_is_built_without_touching_the_network(self):
        # httpx — единственный транспорт pim_api; если модель полезет в сеть,
        # тест упадёт здесь, а не «когда-нибудь на проде».
        with patch('httpx.get', side_effect=AssertionError('PIM must not be called')):
            product = Product.objects.create(pim_id='p1', number='SKU-1', raw_data=self.RAW)
            product.rebuild_search_vector()

        self.assertIsNotNone(Product.objects.get(pk=product.pk).search_vector)

    def test_vector_matches_words_from_every_weighted_source(self):
        product = Product.objects.create(pim_id='p2', number='SKU-2', raw_data=self.RAW)
        product.rebuild_search_vector()

        found = Product.objects.filter(pk=product.pk)
        for term in ['сантехника', 'смесители', 'кухня', 'хром', 'grohe', 'SKU-2', 'однорычажный']:
            with self.subTest(term=term):
                self.assertTrue(
                    found.filter(search_vector=SearchQuery(term, config='russian')).exists(),
                    f'{term!r} не попал в search_vector',
                )

    def test_category_names_are_separate_tokens(self):
        """Разделитель — пробел, а не ''.

        В MainProduct стояло ''.join(...), из-за чего 'Сантехника'+'Смесители'
        склеивались в один токен и по отдельному слову не находились.
        """
        product = Product.objects.create(pim_id='p3', number='SKU-3', raw_data=self.RAW)
        product.rebuild_search_vector()

        self.assertTrue(
            Product.objects.filter(
                pk=product.pk, search_vector=SearchQuery('смесители', config='russian')
            ).exists()
        )

    def test_empty_raw_data_yields_a_vector_over_number_alone(self):
        """0005/0007 оставляют строки с raw_data={} — вектор не должен падать."""
        product = Product.objects.create(pim_id='p4', number='SKU-4', raw_data={})
        product.rebuild_search_vector()

        self.assertTrue(
            Product.objects.filter(
                pk=product.pk, search_vector=SearchQuery('SKU-4', config='russian')
            ).exists()
        )


class ProductDisplayNameTests(TestCase):
    def test_uses_name_when_present(self):
        product = Product.objects.create(pim_id='d1', number='SKU-D1', name='Смеситель')
        self.assertEqual(product.display_name, 'Смеситель')

    def test_falls_back_to_main_product_name_when_unsynced(self):
        product = Product.objects.create(pim_id='d2', number='SKU-D2', name=None)
        MainProduct.objects.create(product=product, article='A1', name='Название от поставщика')
        self.assertEqual(product.display_name, 'Название от поставщика')

    def test_falls_back_to_number_when_nothing_else_exists(self):
        product = Product.objects.create(pim_id='d3', number='SKU-D3', name=None)
        self.assertEqual(product.display_name, 'SKU-D3')
