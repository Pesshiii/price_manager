from typing import Any, Dict


def get_field_details(model) -> Dict[str, Dict[str, Any]]:
    return {
        field.name: {
            'type': field.get_internal_type(),
            'verbose_name': getattr(field, 'verbose_name', field.name),
            'max_length': getattr(field, 'max_length', None),
            'null': getattr(field, 'null', False),
            'blank': getattr(field, 'blank', False),
            'choices': getattr(field, 'choices', None),
            'is_relation': field.is_relation,
            'primary_key': getattr(field, 'primary_key', False),
            'unique': getattr(field, 'unique', False),
        }
        for field in model._meta.get_fields()
        if 'id' not in field.name
    }


def extract_initial_from_post(post, prefix='form', data=None, length=None):
    if data is None:
        data = {}
    rows = []
    total = int(post.get(f'{prefix}-TOTAL_FORMS', 0)) if length is None else length
    for i in range(total):
        rows.append({key: post.get(f'{prefix}-{i}-{key}', value) for key, value in data.items()})
    return rows
