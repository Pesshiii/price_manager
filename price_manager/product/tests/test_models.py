from django.core.exceptions import ValidationError
from django.test import TestCase

from product.models import Brand, Category, CharacteristicType, Product


class CharacteristicTypeValidationTests(TestCase):
    def test_string_coercion(self):
        ct = CharacteristicType.objects.create(name='color', label='Цвет', value_type='string')
        self.assertEqual(ct.validate_value(123), '123')

    def test_integer_coercion(self):
        ct = CharacteristicType.objects.create(name='weight', label='Вес', value_type='integer')
        self.assertEqual(ct.validate_value('5'), 5)
        with self.assertRaises(ValidationError):
            ct.validate_value('not a number')

    def test_float_coercion(self):
        ct = CharacteristicType.objects.create(name='voltage', label='Напряжение', value_type='float')
        self.assertEqual(ct.validate_value('220.5'), 220.5)

    def test_boolean_coercion(self):
        ct = CharacteristicType.objects.create(name='waterproof', label='Влагозащита', value_type='boolean')
        self.assertIs(ct.validate_value('да'), True)
        self.assertIs(ct.validate_value('false'), False)
        with self.assertRaises(ValidationError):
            ct.validate_value('maybe')

    def test_choice_validation(self):
        ct = CharacteristicType.objects.create(
            name='size', label='Размер', value_type='choice', options=['S', 'M', 'L'],
        )
        self.assertEqual(ct.validate_value('M'), 'M')
        with self.assertRaises(ValidationError):
            ct.validate_value('XXL')

    def test_required_blank_raises(self):
        ct = CharacteristicType.objects.create(name='r', label='Req', value_type='string', required=True)
        with self.assertRaises(ValidationError):
            ct.validate_value('')

    def test_optional_blank_returns_none(self):
        ct = CharacteristicType.objects.create(name='o', label='Opt', value_type='string')
        self.assertIsNone(ct.validate_value(''))
        self.assertIsNone(ct.validate_value(None))


class ProductCleanTests(TestCase):
    def setUp(self):
        self.color = CharacteristicType.objects.create(name='color', label='Цвет', value_type='string')
        self.weight = CharacteristicType.objects.create(name='weight', label='Вес', value_type='integer')

    def test_clean_coerces_characteristics(self):
        p = Product(sku='A1', name='Product A', characteristics={'weight': '5', 'color': 'red'})
        p.clean()
        self.assertEqual(p.characteristics, {'weight': 5, 'color': 'red'})

    def test_clean_rejects_unknown_characteristic(self):
        p = Product(sku='A1', name='X', characteristics={'unknown': 'x'})
        with self.assertRaises(ValidationError):
            p.clean()

    def test_clean_required_for_category(self):
        cat = Category.objects.create(name='Электроника')
        self.weight.required = True
        self.weight.save()
        self.weight.categories.add(cat)
        p = Product(sku='A2', name='Y', category=cat, characteristics={'color': 'red'})
        with self.assertRaises(ValidationError):
            p.clean()

    def test_unique_sku(self):
        Product.objects.create(sku='SAME', name='one')
        with self.assertRaises(Exception):
            Product.objects.create(sku='SAME', name='two')


class SlugAutoFillTests(TestCase):
    def test_category_slug_auto(self):
        c = Category.objects.create(name='Электроника')
        self.assertTrue(c.slug)

    def test_brand_slug_auto(self):
        b = Brand.objects.create(name='Acme')
        self.assertEqual(b.slug, 'acme')
