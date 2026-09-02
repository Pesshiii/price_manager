from django.db import IntegrityError
from django.test import TestCase

from product.models import Category, Product


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
