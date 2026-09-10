from django.test import TestCase

from .forms import SupplierForm
from .models import Currency, Supplier


def _layout_field_names(layout):
    """Имена полей, реально попавшие в crispy Layout, включая вложенные Div."""
    names = []
    for field in layout.fields:
        if isinstance(field, str):
            names.append(field)
            continue
        names.extend(_layout_field_names(field) if hasattr(field, 'fields') else [])
        if hasattr(field, 'field') and isinstance(getattr(field, 'field', None), str):
            names.append(field.field)
    return names


class SupplierPriorityFieldTests(TestCase):
    """Приоритеты поставщика: меньше — выше, NULL — не проранжирован."""

    def setUp(self):
        self.currency = Currency.objects.get_or_create(name='KZT', value=1)[0]

    def make_supplier(self, name, **kwargs):
        return Supplier.objects.create(
            name=name,
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=7,
            **kwargs,
        )

    def test_priorities_default_to_null(self):
        """Миграция никому ничего не проставляет — поставщик приезжает непроранжированным."""
        supplier = self.make_supplier('Без приоритетов')

        self.assertIsNone(supplier.price_priority)
        self.assertIsNone(supplier.stock_priority)

    def test_priorities_are_stored_independently(self):
        supplier = self.make_supplier('С приоритетами', price_priority=1, stock_priority=5)
        supplier.refresh_from_db()

        self.assertEqual(supplier.price_priority, 1)
        self.assertEqual(supplier.stock_priority, 5)


class SupplierFormPriorityTests(TestCase):
    """Supplier не зарегистрирован в админке, так что форма — единственное место правки."""

    def test_priorities_are_in_form_fields(self):
        self.assertIn('price_priority', SupplierForm.Meta.fields)
        self.assertIn('stock_priority', SupplierForm.Meta.fields)

    def test_priorities_are_rendered_by_the_layout(self):
        """В Meta.fields мало: без места в Layout crispy их просто не отрисует."""
        form = SupplierForm(url='/suppliers/1/update')

        rendered = _layout_field_names(form.helper.layout)

        self.assertIn('price_priority', rendered)
        self.assertIn('stock_priority', rendered)


class DeliveryDaysNullStockTests(TestCase):
    """`stock is None` — «ни разу не синхронизировался», а не ноль."""

    def setUp(self):
        currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Срочный',
            currency=currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=2,
            delivery_days_navailable=30,
        )

    def test_positive_stock_uses_available_days(self):
        self.assertEqual(self.supplier.get_delivery_days_for_stock(5), 2)

    def test_zero_stock_uses_navailable_days(self):
        self.assertEqual(self.supplier.get_delivery_days_for_stock(0), 30)

    def test_unknown_stock_still_returns_a_term(self):
        """Срок обязан показаться, а не остаться пустым."""
        self.assertEqual(self.supplier.get_delivery_days_for_stock(None), 30)
