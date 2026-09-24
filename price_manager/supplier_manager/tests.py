import importlib
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from django.forms import modelform_factory
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from main_product_manager.models import MainProduct

from .forms import IntervalField, SupplierForm
from .models import Currency, Supplier, format_interval

migration_0012 = importlib.import_module('supplier_manager.migrations.0012_supplier_update_days')
migration_0013 = importlib.import_module('supplier_manager.migrations.0013_supplier_unique_priorities')


def _supplier(name, **kwargs):
    currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
    kwargs.setdefault('delivery_days_available', 1)
    kwargs.setdefault('delivery_days_navailable', 7)
    return Supplier.objects.create(name=name, currency=currency, **kwargs)


class IntervalFieldTests(TestCase):
    """Интервал вводится «число + дни/недели», хранится в днях."""

    def setUp(self):
        self.field = IntervalField(required=False)

    def test_weeks_are_stored_as_days(self):
        self.assertEqual(self.field.clean(['2', 'week']), 14)
        self.assertEqual(self.field.clean(['10', 'day']), 10)

    def test_empty_amount_means_untracked(self):
        self.assertIsNone(self.field.clean(['', 'week']))

    def test_zero_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.field.clean(['0', 'day'])

    def test_decompress_prefers_weeks_when_divisible(self):
        widget = self.field.widget
        self.assertEqual(widget.decompress(14), [2, 'week'])
        self.assertEqual(widget.decompress(10), [10, 'day'])
        self.assertEqual(widget.decompress(None), [None, 'day'])

    def test_form_round_trip(self):
        """«2 недели» сохраняется как 14 и при открытии снова показывается неделями."""
        supplier = _supplier('Интервалы')
        data = {
            'name': supplier.name, 'currency': supplier.currency_id,
            'delivery_days_available': 1, 'delivery_days_navailable': 7,
            'msg_available': 'Есть', 'msg_navailable': 'Нет',
            'price_update_days_0': '2', 'price_update_days_1': 'week',
            'stock_update_days_0': '', 'stock_update_days_1': 'day',
        }
        form = SupplierForm(data, instance=supplier, url='/x')
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        supplier.refresh_from_db()
        self.assertEqual(supplier.price_update_days, 14)
        self.assertIsNone(supplier.stock_update_days)

    def test_format_interval(self):
        self.assertEqual(format_interval(14), '2 нед.')
        self.assertEqual(format_interval(3), '3 дн.')
        self.assertIsNone(format_interval(None))


class Migration0012RateToDaysTests(TestCase):
    def test_labels_map_to_days(self):
        self.assertEqual(migration_0012.rate_to_days('Каждый день'), 1)
        self.assertEqual(migration_0012.rate_to_days('Каждую неделю'), 7)
        self.assertEqual(migration_0012.rate_to_days('Каждые три недели'), 21)
        self.assertIsNone(migration_0012.rate_to_days(''))
        self.assertIsNone(migration_0012.rate_to_days(None))

    def test_backwards_rounds_to_nearest_label(self):
        self.assertEqual(migration_0012.days_to_rate(None), '')
        self.assertEqual(migration_0012.days_to_rate(7), 'Каждую неделю')
        self.assertEqual(migration_0012.days_to_rate(30), 'Каждые три недели')


class UpdateStatusTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_statuses(self):
        s = _supplier('Статусы', price_update_days=None, stock_update_days=3)
        self.assertEqual(s.update_status('price', now=self.now), 'untracked')
        self.assertEqual(s.update_status('stock', now=self.now), 'never')

        s.stock_updated_at = self.now - timedelta(days=3) + timedelta(seconds=1)
        self.assertEqual(s.update_status('stock', now=self.now), 'ok')
        s.stock_updated_at = self.now - timedelta(days=3)
        self.assertEqual(s.update_status('stock', now=self.now), 'overdue')


class SupplierListViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username='supplier-list', password='pw'))

    def _get(self, **params):
        return self.client.get(reverse('supplier'), params)

    def _count_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            self._get()
        return len(ctx.captured_queries)

    def test_query_count_does_not_grow_with_suppliers(self):
        _supplier('Один')
        self._get()  # прогрев сессии
        one = self._count_queries()
        for name in ('Два', 'Три', 'Четыре'):
            s = _supplier(name)
            MainProduct.objects.create(supplier=s, article=name, name=name)
        self.assertEqual(self._count_queries(), one)

    def test_priority_sort_puts_unranked_last_both_ways(self):
        _supplier('Б', price_priority=2)
        _supplier('А')
        _supplier('В', price_priority=1)
        for direction, expected in (('asc', ['В', 'Б', 'А']), ('desc', ['Б', 'В', 'А'])):
            response = self._get(sort='price_priority', dir=direction)
            names = [row['name'] for row in response.context['suppliers']]
            self.assertEqual(names, expected)

    def test_price_cells_follow_header_order(self):
        s = _supplier('Цены')
        MainProduct.objects.create(supplier=s, article='A', name='A', basic_price=10, prime_cost=None)
        response = self._get()
        row = response.context['suppliers'][0]
        self.assertEqual([p['key'] for p in row['prices']],
                         [key for key, _ in response.context['price_columns']])
        self.assertEqual(row['basic_price'], 0)
        self.assertEqual(row['prime_cost'], 1)
        html = response.content.decode()
        cells = re.findall(r'supplier-price-(\w+)', html)
        self.assertEqual(cells, ['basic_price', 'prime_cost', 'm_price', 'wholesale_price'])

    def test_status_badges_rendered(self):
        _supplier('Бейджи', price_update_days=7, stock_update_days=None)
        html = self._get().content.decode()
        self.assertIn('supplier-status-never', html)
        self.assertIn('supplier-status-untracked', html)


class SupplierPriorityUpdateTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username='priority', password='pw'))
        self.supplier = _supplier('Приоритет', price_priority=1)

    def _post(self, field, value):
        return self.client.post(
            reverse('supplier-priority', args=[self.supplier.pk, field]), {'value': value},
        )

    def test_saves_value(self):
        response = self._post('stock_priority', '1')
        self.assertEqual(response.status_code, 200)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.stock_priority, 1)
        self.assertIn('is-valid', response.content.decode())

    def test_empty_clears(self):
        self._post('price_priority', '')
        self.supplier.refresh_from_db()
        self.assertIsNone(self.supplier.price_priority)

    def test_invalid_is_not_saved(self):
        response = self._post('price_priority', '-1')
        self.assertIn('is-invalid', response.content.decode())
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.price_priority, 1)

    def test_unknown_field_is_404(self):
        self.assertEqual(self._post('name', 'x').status_code, 404)

    def test_taken_level_is_shared_and_neighbours_untouched(self):
        other = _supplier('Сосед', price_priority=2)
        response = self._post('price_priority', '2')
        html = response.content.decode()

        self.supplier.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.supplier.price_priority, 2)
        self.assertEqual(other.price_priority, 2)
        self.assertIn('is-valid', html)
        self.assertNotIn('hx-swap-oob', html)


def _priorities(field='price_priority'):
    return dict(Supplier.objects.filter(**{f'{field}__isnull': False}).values_list('name', field))


def _set(name, value, field='price_priority'):
    supplier = Supplier.objects.get(name=name)
    setattr(supplier, field, value)
    supplier.save()
    return supplier


class PriorityLevelTests(TestCase):
    """Приоритет — уровень: номер может быть общим, остальных он не сдвигает."""

    def test_several_suppliers_share_a_level(self):
        _supplier('a', price_priority=1)
        _supplier('b', price_priority=1)
        _supplier('c', price_priority=2)
        self.assertEqual(_priorities(), {'a': 1, 'b': 1, 'c': 2})

    def test_gaps_are_kept(self):
        _supplier('a', price_priority=1)
        _supplier('b', price_priority=10)
        _set('a', None)
        self.assertEqual(_priorities(), {'b': 10})

    def test_deleting_does_not_renumber(self):
        _supplier('a', price_priority=1)
        _supplier('b', price_priority=2)
        Supplier.objects.get(name='a').delete()
        self.assertEqual(_priorities(), {'b': 2})

    def test_fields_are_independent(self):
        _supplier('a', price_priority=1, stock_priority=1)
        _set('a', None, field='stock_priority')
        self.assertEqual(_priorities('price_priority'), {'a': 1})
        self.assertEqual(_priorities('stock_priority'), {})

    def test_form_accepts_taken_level(self):
        _supplier('a', price_priority=1)
        b = _supplier('b')
        form = modelform_factory(Supplier, fields=['price_priority'])({'price_priority': 1}, instance=b)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(_priorities(), {'a': 1, 'b': 1})


class Migration0013RenumberTests(TestCase):
    def test_duplicates_and_gaps_become_dense_in_order(self):
        pairs = [('a', 1), ('b', 1), ('c', 2), ('d', 5), ('e', 5)]
        # e уже стоит на 5 — его номер не меняется, и в результат он не попадает.
        self.assertEqual(migration_0013.renumber(pairs), {'b': 2, 'c': 3, 'd': 4})

    def test_dense_data_untouched(self):
        self.assertEqual(migration_0013.renumber([('a', 1), ('b', 2)]), {})


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
        self.make_supplier('Первый', stock_priority=1)
        supplier = self.make_supplier('С приоритетами', price_priority=1, stock_priority=2)
        supplier.refresh_from_db()

        self.assertEqual(supplier.price_priority, 1)
        self.assertEqual(supplier.stock_priority, 2)


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
