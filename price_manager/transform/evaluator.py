from typing import Union


def evaluate_condition(condition: Union[dict, None], feed_data: dict, product) -> bool:
    if condition is None:
        return True
    op = condition['op']
    if op in ('AND', 'OR', 'NOT'):
        if op == 'NOT':
            return not evaluate_condition(condition['condition'], feed_data, product)
        results = [evaluate_condition(c, feed_data, product) for c in condition['conditions']]
        return all(results) if op == 'AND' else any(results)
    # leaf comparison
    source = condition['source']
    key = condition.get('key')
    if source == 'feed':
        actual = feed_data.get(key)
    elif source == 'char':
        actual = product.characteristics.get(key)
    elif source == 'brand':
        actual = product.brand.name
    elif source == 'category':
        actual = product.category.name
    else:
        raise ValueError(f"Unknown condition source: {source!r}")
    expected = condition['value']
    if op == '==':
        return actual == expected
    if op == '!=':
        return actual != expected
    if op == '<':
        return actual < expected
    if op == '<=':
        return actual <= expected
    if op == '>':
        return actual > expected
    if op == '>=':
        return actual >= expected
    raise ValueError(f"Unknown condition op: {op!r}")
