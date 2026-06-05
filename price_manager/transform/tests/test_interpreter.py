import unittest
from transform.interpreter import evaluate_formula


class ProductStub:
    """Duck-typed product for interpreter tests — no ORM needed."""
    def __init__(self, characteristics=None, brand_name='ACME', category_name='General'):
        self.characteristics = characteristics or {}
        self.brand = type('Brand', (), {'name': brand_name})()
        self.category = type('Category', (), {'name': category_name})()


FEED = {'price': 100, 'status': 'В наличии', 'weight': 2.5}
PRODUCT = ProductStub(characteristics={'color': 'red', 'size': 'XL'})


# ---------------------------------------------------------------------------
# Cycle 1: literal (tracer bullet)
# ---------------------------------------------------------------------------

class LiteralFormulaTest(unittest.TestCase):
    def test_literal_returns_value(self):
        result = evaluate_formula({'type': 'literal', 'value': 42}, {}, PRODUCT)
        self.assertEqual(result, 42)

    def test_literal_string(self):
        result = evaluate_formula({'type': 'literal', 'value': 'hello'}, {}, PRODUCT)
        self.assertEqual(result, 'hello')

    def test_literal_none(self):
        result = evaluate_formula({'type': 'literal', 'value': None}, {}, PRODUCT)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Cycle 2: copy from feed
# ---------------------------------------------------------------------------

class CopyFromFeedTest(unittest.TestCase):
    def test_copy_feed_returns_value(self):
        result = evaluate_formula({'type': 'copy', 'source': 'feed', 'key': 'price'}, FEED, PRODUCT)
        self.assertEqual(result, 100)

    def test_copy_feed_missing_key_returns_none(self):
        result = evaluate_formula({'type': 'copy', 'source': 'feed', 'key': 'nonexistent'}, FEED, PRODUCT)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Cycle 3: copy from char
# ---------------------------------------------------------------------------

class CopyFromCharTest(unittest.TestCase):
    def test_copy_char_returns_characteristic(self):
        result = evaluate_formula({'type': 'copy', 'source': 'char', 'key': 'color'}, FEED, PRODUCT)
        self.assertEqual(result, 'red')

    def test_copy_char_missing_key_returns_none(self):
        result = evaluate_formula({'type': 'copy', 'source': 'char', 'key': 'missing'}, FEED, PRODUCT)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Cycle 4: arithmetic
# ---------------------------------------------------------------------------

def _arith(op, left_val, right_val):
    return {
        'type': 'arithmetic',
        'op': op,
        'left': {'type': 'literal', 'value': left_val},
        'right': {'type': 'literal', 'value': right_val},
    }


class ArithmeticFormulaTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(evaluate_formula(_arith('+', 3, 4), {}, PRODUCT), 7)

    def test_subtract(self):
        self.assertEqual(evaluate_formula(_arith('-', 10, 3), {}, PRODUCT), 7)

    def test_multiply(self):
        self.assertEqual(evaluate_formula(_arith('*', 3, 4), {}, PRODUCT), 12)

    def test_divide(self):
        self.assertEqual(evaluate_formula(_arith('/', 10, 2), {}, PRODUCT), 5)

    def test_divide_by_zero_raises(self):
        with self.assertRaises(ZeroDivisionError):
            evaluate_formula(_arith('/', 10, 0), {}, PRODUCT)


# ---------------------------------------------------------------------------
# Cycle 5: map
# ---------------------------------------------------------------------------

class MapFormulaTest(unittest.TestCase):
    MAP_FORMULA = {
        'type': 'map',
        'input': {'type': 'copy', 'source': 'feed', 'key': 'status'},
        'mapping': {'В наличии': True, 'Нет в наличии': False},
        'default': None,
    }

    def test_map_hit(self):
        result = evaluate_formula(self.MAP_FORMULA, {'status': 'В наличии'}, PRODUCT)
        self.assertTrue(result)

    def test_map_another_hit(self):
        result = evaluate_formula(self.MAP_FORMULA, {'status': 'Нет в наличии'}, PRODUCT)
        self.assertFalse(result)

    def test_map_miss_returns_default(self):
        result = evaluate_formula(self.MAP_FORMULA, {'status': 'Неизвестно'}, PRODUCT)
        self.assertIsNone(result)

    def test_map_non_null_default(self):
        formula = {**self.MAP_FORMULA, 'default': 'unknown'}
        result = evaluate_formula(formula, {'status': 'X'}, PRODUCT)
        self.assertEqual(result, 'unknown')


# ---------------------------------------------------------------------------
# Cycle 6: if formula
# ---------------------------------------------------------------------------

class IfFormulaTest(unittest.TestCase):
    def _if(self, condition):
        return {
            'type': 'if',
            'condition': condition,
            'then': {'type': 'literal', 'value': 'yes'},
            'else': {'type': 'literal', 'value': 'no'},
        }

    def test_if_null_condition_returns_then(self):
        result = evaluate_formula(self._if(None), {}, PRODUCT)
        self.assertEqual(result, 'yes')

    def test_if_true_condition_returns_then(self):
        cond = {'op': '==', 'source': 'feed', 'key': 'x', 'value': 1}
        result = evaluate_formula(self._if(cond), {'x': 1}, PRODUCT)
        self.assertEqual(result, 'yes')

    def test_if_false_condition_returns_else(self):
        cond = {'op': '==', 'source': 'feed', 'key': 'x', 'value': 1}
        result = evaluate_formula(self._if(cond), {'x': 99}, PRODUCT)
        self.assertEqual(result, 'no')


# ---------------------------------------------------------------------------
# Cycle 7: nesting — arithmetic using copy + literal
# ---------------------------------------------------------------------------

class NestedFormulaTest(unittest.TestCase):
    def test_arithmetic_with_copy_and_literal(self):
        formula = {
            'type': 'arithmetic',
            'op': '*',
            'left': {'type': 'copy', 'source': 'feed', 'key': 'price'},
            'right': {'type': 'literal', 'value': 0.9},
        }
        result = evaluate_formula(formula, {'price': 200}, PRODUCT)
        self.assertAlmostEqual(result, 180.0)
