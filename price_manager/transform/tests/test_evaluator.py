import unittest
from transform.evaluator import evaluate_condition


class ProductStub:
    """Duck-typed product for evaluator tests — no ORM needed."""
    def __init__(self, characteristics=None, brand_name='Nike', category_name='Shoes'):
        self.characteristics = characteristics or {}
        self.brand = type('Brand', (), {'name': brand_name})()
        self.category = type('Category', (), {'name': category_name})()


FEED = {'price': 100, 'status': 'active', 'qty': 5}
PRODUCT = ProductStub(characteristics={'color': 'red', 'size': 10})


# ---------------------------------------------------------------------------
# Cycle 1: None condition (tracer bullet)
# ---------------------------------------------------------------------------

class NoneConditionTest(unittest.TestCase):
    def test_none_condition_returns_true(self):
        self.assertTrue(evaluate_condition(None, {}, PRODUCT))


# ---------------------------------------------------------------------------
# Cycle 2: == leaf with feed source
# ---------------------------------------------------------------------------

class EqualityLeafTest(unittest.TestCase):
    def _leaf(self, op, source, key, value):
        c = {'op': op, 'source': source, 'value': value}
        if key is not None:
            c['key'] = key
        return c

    def test_eq_feed_true(self):
        c = self._leaf('==', 'feed', 'status', 'active')
        self.assertTrue(evaluate_condition(c, FEED, PRODUCT))

    def test_eq_feed_false(self):
        c = self._leaf('==', 'feed', 'status', 'inactive')
        self.assertFalse(evaluate_condition(c, FEED, PRODUCT))


# ---------------------------------------------------------------------------
# Cycle 3: other comparison operators
# ---------------------------------------------------------------------------

class ComparisonOperatorTest(unittest.TestCase):
    def _feed_leaf(self, op, key, value):
        return {'op': op, 'source': 'feed', 'key': key, 'value': value}

    def test_ne_true(self):
        self.assertTrue(evaluate_condition(self._feed_leaf('!=', 'status', 'inactive'), FEED, PRODUCT))

    def test_ne_false(self):
        self.assertFalse(evaluate_condition(self._feed_leaf('!=', 'status', 'active'), FEED, PRODUCT))

    def test_lt_true(self):
        self.assertTrue(evaluate_condition(self._feed_leaf('<', 'price', 200), FEED, PRODUCT))

    def test_lt_false(self):
        self.assertFalse(evaluate_condition(self._feed_leaf('<', 'price', 50), FEED, PRODUCT))

    def test_lte_equal(self):
        self.assertTrue(evaluate_condition(self._feed_leaf('<=', 'price', 100), FEED, PRODUCT))

    def test_gt_true(self):
        self.assertTrue(evaluate_condition(self._feed_leaf('>', 'price', 50), FEED, PRODUCT))

    def test_gte_equal(self):
        self.assertTrue(evaluate_condition(self._feed_leaf('>=', 'price', 100), FEED, PRODUCT))


# ---------------------------------------------------------------------------
# Cycle 4: leaf sources — char, brand, category
# ---------------------------------------------------------------------------

class LeafSourceTest(unittest.TestCase):
    def test_char_source_hit(self):
        c = {'op': '==', 'source': 'char', 'key': 'color', 'value': 'red'}
        self.assertTrue(evaluate_condition(c, {}, PRODUCT))

    def test_char_source_miss(self):
        c = {'op': '==', 'source': 'char', 'key': 'color', 'value': 'blue'}
        self.assertFalse(evaluate_condition(c, {}, PRODUCT))

    def test_brand_source(self):
        c = {'op': '==', 'source': 'brand', 'value': 'Nike'}
        self.assertTrue(evaluate_condition(c, {}, PRODUCT))

    def test_brand_source_miss(self):
        c = {'op': '==', 'source': 'brand', 'value': 'Adidas'}
        self.assertFalse(evaluate_condition(c, {}, PRODUCT))

    def test_category_source(self):
        c = {'op': '==', 'source': 'category', 'value': 'Shoes'}
        self.assertTrue(evaluate_condition(c, {}, PRODUCT))

    def test_category_source_miss(self):
        c = {'op': '==', 'source': 'category', 'value': 'Bags'}
        self.assertFalse(evaluate_condition(c, {}, PRODUCT))


# ---------------------------------------------------------------------------
# Cycle 5: logical operators — AND, OR, NOT
# ---------------------------------------------------------------------------

def _true_leaf():
    return {'op': '==', 'source': 'feed', 'key': 'status', 'value': 'active'}


def _false_leaf():
    return {'op': '==', 'source': 'feed', 'key': 'status', 'value': 'inactive'}


class LogicalOperatorTest(unittest.TestCase):
    def test_and_all_true(self):
        c = {'op': 'AND', 'conditions': [_true_leaf(), _true_leaf()]}
        self.assertTrue(evaluate_condition(c, FEED, PRODUCT))

    def test_and_one_false(self):
        c = {'op': 'AND', 'conditions': [_true_leaf(), _false_leaf()]}
        self.assertFalse(evaluate_condition(c, FEED, PRODUCT))

    def test_and_all_false(self):
        c = {'op': 'AND', 'conditions': [_false_leaf(), _false_leaf()]}
        self.assertFalse(evaluate_condition(c, FEED, PRODUCT))

    def test_or_one_true(self):
        c = {'op': 'OR', 'conditions': [_false_leaf(), _true_leaf()]}
        self.assertTrue(evaluate_condition(c, FEED, PRODUCT))

    def test_or_all_false(self):
        c = {'op': 'OR', 'conditions': [_false_leaf(), _false_leaf()]}
        self.assertFalse(evaluate_condition(c, FEED, PRODUCT))

    def test_not_true_becomes_false(self):
        c = {'op': 'NOT', 'condition': _true_leaf()}
        self.assertFalse(evaluate_condition(c, FEED, PRODUCT))

    def test_not_false_becomes_true(self):
        c = {'op': 'NOT', 'condition': _false_leaf()}
        self.assertTrue(evaluate_condition(c, FEED, PRODUCT))

    def test_nested_and_inside_not(self):
        inner = {'op': 'AND', 'conditions': [_true_leaf(), _true_leaf()]}
        c = {'op': 'NOT', 'condition': inner}
        self.assertFalse(evaluate_condition(c, FEED, PRODUCT))
