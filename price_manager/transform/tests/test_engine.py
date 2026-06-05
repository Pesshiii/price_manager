from django.test import TestCase

from supplier_feed.models import SupplierFeed, SupplierFeedEntry
from supplier_feed.tests.fixtures import make_feed_mapping, make_product, make_supplier
from transform.models import SnapshotField, TransformRule


def make_field(slug='price', name='Цена', value_type='number'):
    sf, _ = SnapshotField.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'value_type': value_type},
    )
    return sf


def make_entry(feed_mapping, data=None):
    supplier = feed_mapping.supplier
    feed = SupplierFeed.objects.create(
        supplier=supplier,
        feed_mapping=feed_mapping,
        status='done',
    )
    return SupplierFeedEntry.objects.create(
        feed=feed,
        supplier_sku='A001',
        data=data or {},
    )


def make_rule(feed_mapping, field, priority=10, condition=None, formula=None):
    if formula is None:
        formula = {'type': 'literal', 'value': 100}
    return TransformRule.objects.create(
        feed_mapping=feed_mapping,
        target_field=field,
        priority=priority,
        condition=condition,
        formula=formula,
    )


# --- Cycle 1: tracer bullet — single rule, condition=None, fires and returns {slug: value} ---

class SingleRuleFiresTest(TestCase):
    def test_unconditional_rule_returns_slug_value(self):
        from transform.engine import apply_rules
        fm = make_feed_mapping()
        product = make_product()
        field = make_field('price')
        make_rule(fm, field, formula={'type': 'literal', 'value': 42})
        entry = make_entry(fm)

        result = apply_rules(fm, entry, product)

        self.assertEqual(result, {'price': 42})


# --- Cycle 2: priority — higher priority (lower int) wins; lower-priority rule skipped ---

class PriorityTest(TestCase):
    def test_lower_int_priority_wins(self):
        from transform.engine import apply_rules
        fm = make_feed_mapping()
        product = make_product()
        field = make_field('price')
        make_rule(fm, field, priority=10, formula={'type': 'literal', 'value': 'winner'})
        make_rule(fm, field, priority=20, formula={'type': 'literal', 'value': 'loser'})
        entry = make_entry(fm)

        result = apply_rules(fm, entry, product)

        self.assertEqual(result, {'price': 'winner'})

    def test_lower_priority_rule_not_evaluated_once_field_claimed(self):
        """Lower-priority rule is skipped entirely — field not overwritten."""
        from transform.engine import apply_rules
        fm = make_feed_mapping()
        product = make_product()
        field = make_field('price')
        make_rule(fm, field, priority=1, formula={'type': 'literal', 'value': 'first'})
        make_rule(fm, field, priority=99, formula={'type': 'literal', 'value': 'second'})
        entry = make_entry(fm)

        result = apply_rules(fm, entry, product)

        self.assertEqual(result['price'], 'first')
        self.assertNotEqual(result['price'], 'second')


# --- Cycle 3: condition false → skip; lower-priority rule for same field fires instead ---

class ConditionFalseSkipsTest(TestCase):
    def test_false_condition_skips_rule_and_fallback_fires(self):
        from transform.engine import apply_rules
        fm = make_feed_mapping()
        product = make_product()
        field = make_field('price')
        # prio=1: condition never true
        never_true = {'source': 'feed', 'key': 'missing_key', 'op': '==', 'value': 'impossible'}
        make_rule(fm, field, priority=1, condition=never_true, formula={'type': 'literal', 'value': 'blocked'})
        # prio=2: fallback, condition=None
        make_rule(fm, field, priority=2, condition=None, formula={'type': 'literal', 'value': 'fallback'})
        entry = make_entry(fm, data={})

        result = apply_rules(fm, entry, product)

        self.assertEqual(result, {'price': 'fallback'})


# --- Cycle 4: no firing rule → field absent from result (not None) ---

class NoFiringRuleAbsentTest(TestCase):
    def test_field_absent_when_no_rule_fires(self):
        from transform.engine import apply_rules
        fm = make_feed_mapping()
        product = make_product()
        field = make_field('price')
        never_true = {'source': 'feed', 'key': 'missing_key', 'op': '==', 'value': 'impossible'}
        make_rule(fm, field, priority=1, condition=never_true, formula={'type': 'literal', 'value': 99})
        entry = make_entry(fm, data={})

        result = apply_rules(fm, entry, product)

        self.assertNotIn('price', result)
        self.assertIsNone(result.get('price'))  # absent means .get() returns None too


# --- Cycle 5: two different fields, both fire independently ---

class TwoFieldsTest(TestCase):
    def test_rules_for_different_fields_both_fire(self):
        from transform.engine import apply_rules
        fm = make_feed_mapping()
        product = make_product()
        price_field = make_field('price', 'Цена', 'number')
        stock_field = make_field('stock', 'Остаток', 'number')
        make_rule(fm, price_field, priority=10, formula={'type': 'literal', 'value': 500})
        make_rule(fm, stock_field, priority=10, formula={'type': 'literal', 'value': 3})
        entry = make_entry(fm)

        result = apply_rules(fm, entry, product)

        self.assertEqual(result, {'price': 500, 'stock': 3})
