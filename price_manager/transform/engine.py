from transform.evaluator import evaluate_condition
from transform.interpreter import evaluate_formula
from transform.models import TransformRule


def apply_rules(feed_mapping, feed_entry, product) -> dict:
    rules = TransformRule.objects.filter(feed_mapping=feed_mapping).order_by('priority')
    result = {}
    for rule in rules:
        slug = rule.target_field.slug
        if slug in result:
            continue
        if evaluate_condition(rule.condition, feed_entry.data, product):
            result[slug] = evaluate_formula(rule.formula, feed_entry.data, product)
    return result
