"""Tests for context-driven facets on ProductViewSet.

Facets are computed from the *context set* — products matching only the
general filters (q, brand, category, status).  char__ params are stripped
before building that set so that selecting one characteristic doesn't collapse
the widget list or skew the bucket counts of others (Amazon-style faceting).

CharacteristicType widgets are shown only for types linked (M2M) to categories
that appear in the context set OR any of their MPTT ancestors.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from product.models import Brand, Category, CharacteristicType, Product


@override_settings(SECURE_SSL_REDIRECT=False)
class FacetsViewTests(TestCase):
    """Covers every decision in ADR 0010."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='u', password='p')

        # Category tree:
        #   electronics (root)
        #     └─ phones (child)
        #   tools (separate root)
        cls.electronics = Category.objects.create(name='Электроника')
        cls.phones = Category.objects.create(name='Телефоны', parent=cls.electronics)
        cls.tools = Category.objects.create(name='Инструменты')

        # CharacteristicType setup:
        #   color   → linked to electronics (parent of phones)
        #   weight  → linked to phones (leaf)
        #   voltage → linked to tools (sibling branch)
        #   material → not linked to any category
        cls.ct_color = CharacteristicType.objects.create(
            name='color', label='Цвет', value_type='string', unit=''
        )
        cls.ct_color.categories.set([cls.electronics])

        cls.ct_weight = CharacteristicType.objects.create(
            name='weight', label='Вес', value_type='integer', unit='г'
        )
        cls.ct_weight.categories.set([cls.phones])

        cls.ct_voltage = CharacteristicType.objects.create(
            name='voltage', label='Напряжение', value_type='integer', unit='В'
        )
        cls.ct_voltage.categories.set([cls.tools])

        cls.ct_material = CharacteristicType.objects.create(
            name='material', label='Материал', value_type='string', unit=''
        )
        # ct_material intentionally has no categories

        # Products
        cls.phone1 = Product.objects.create(
            sku='PH1', name='Смартфон 1', category=cls.phones, status='active',
            characteristics={'color': 'red', 'weight': 200},
        )
        cls.phone2 = Product.objects.create(
            sku='PH2', name='Смартфон 2', category=cls.phones, status='active',
            characteristics={'color': 'blue', 'weight': 300},
        )
        cls.tool1 = Product.objects.create(
            sku='T1', name='Дрель', category=cls.tools, status='active',
            characteristics={'voltage': 220, 'material': 'metal'},
        )
        cls.no_cat = Product.objects.create(
            sku='NC1', name='Без категории', category=None, status='active',
            characteristics={'color': 'green'},
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _facets(self, query=''):
        url = reverse('product_api:product-facets')
        resp = self.client.get(url + query)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json()

    # ── tracer bullet ────────────────────────────────────────────────────────

    def test_linked_type_appears_with_buckets(self):
        """Basic happy path: type linked to context category surfaces as widget."""
        data = self._facets('?category=' + str(self.phones.id))
        self.assertIn('color', data)
        self.assertIn('weight', data)
        self.assertEqual(data['color']['label'], 'Цвет')
        self.assertEqual(data['weight']['unit'], 'г')
        self.assertIsInstance(data['color']['buckets'], list)
        self.assertGreater(len(data['color']['buckets']), 0)

    # ── ancestor expansion ───────────────────────────────────────────────────

    def test_parent_category_type_appears_for_child_products(self):
        """color is linked to electronics (parent); phones products must surface it."""
        data = self._facets('?category=' + str(self.phones.id))
        self.assertIn('color', data)

    # ── sibling branch excluded ──────────────────────────────────────────────

    def test_type_from_sibling_branch_excluded(self):
        """voltage is linked to tools; filtering by phones branch must not include it."""
        data = self._facets('?category=' + str(self.phones.id))
        self.assertNotIn('voltage', data)

    # ── char__ filters don't affect widget set ───────────────────────────────

    def test_char_filter_does_not_change_widget_keys(self):
        """Adding char__color=red must not drop the color or weight widgets."""
        base = '?category=' + str(self.phones.id)
        data_without = self._facets(base)
        data_with = self._facets(base + '&char__color=red')
        self.assertEqual(set(data_without.keys()), set(data_with.keys()))

    # ── bucket counts computed on context set (no char__ applied) ────────────

    def test_bucket_counts_ignore_char_filter(self):
        """Even with char__color=red in the URL, both color values must appear in buckets."""
        data = self._facets(
            '?category=' + str(self.phones.id) + '&char__color=red'
        )
        color_values = {b['value'] for b in data['color']['buckets']}
        # context set has phones products with both red and blue
        self.assertIn('red', color_values)
        self.assertIn('blue', color_values)

    # ── unlinked char type excluded ──────────────────────────────────────────

    def test_unlinked_char_type_never_appears(self):
        """material has no category M2M; it must never surface as a widget."""
        # Use no category filter so all products (including tools) are in context.
        data = self._facets()
        self.assertNotIn('material', data)

    # ── empty widget excluded ────────────────────────────────────────────────

    def test_type_with_no_values_in_context_excluded(self):
        """weight is linked to phones; filtering to tools context → no weight widget."""
        data = self._facets('?category=' + str(self.tools.id))
        self.assertNotIn('weight', data)

    # ── no categories in context → {} ────────────────────────────────────────

    def test_no_categories_in_context_returns_empty_dict(self):
        """All context products have category=NULL → no widgets → empty response."""
        data = self._facets('?category__isnull=true')
        self.assertEqual(data, {})

    # ── product without category excluded from widget determination ───────────

    def test_no_cat_product_chars_excluded_when_type_unlinked(self):
        """no_cat product has color=green, but its char only surfaces if the type
        is linked through *another* product's category in the context.

        Here we filter to only no-cat products; since there are no categories,
        the widget list must be empty.
        """
        data = self._facets('?category__isnull=true')
        self.assertNotIn('color', data)
