from typing import Any
from transform.evaluator import evaluate_condition


def evaluate_formula(formula: dict, feed_data: dict, product) -> Any:
    t = formula['type']
    if t == 'literal':
        return formula['value']
    if t == 'copy':
        source = formula['source']
        key = formula['key']
        if source == 'feed':
            return feed_data.get(key)
        if source == 'char':
            return product.characteristics.get(key)
    if t == 'arithmetic':
        left = evaluate_formula(formula['left'], feed_data, product)
        right = evaluate_formula(formula['right'], feed_data, product)
        op = formula['op']
        if op == '+':
            return left + right
        if op == '-':
            return left - right
        if op == '*':
            return left * right
        if op == '/':
            return left / right  # ZeroDivisionError propagates naturally
    if t == 'map':
        value = evaluate_formula(formula['input'], feed_data, product)
        return formula['mapping'].get(value, formula.get('default'))
    if t == 'if':
        branch = 'then' if evaluate_condition(formula['condition'], feed_data, product) else 'else'
        return evaluate_formula(formula[branch], feed_data, product)
    raise ValueError(f"Unknown formula type: {t!r}")
