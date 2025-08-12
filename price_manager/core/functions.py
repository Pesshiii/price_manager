import pandas as pd
from io import StringIO
from .models import *
# Работа с моделями

def get_field_details(Model) -> dict:
  '''Возвращает полное описание всех столбцов'''
  return {
    field.name: {
        'type': field.get_internal_type(),
        'verbose_name': getattr(field, 'verbose_name', field.name),
        'max_length': getattr(field, 'max_length', None),
        'null': getattr(field, 'null', False),
        'blank': getattr(field, 'blank', False),
        'choices': getattr(field, 'choices', None),
        'is_relation': field.is_relation,
        'primary_key':getattr(field, 'primary_key', False),
        'unique':getattr(field, 'unique', False)
    }
    for field in Model._meta.get_fields() if not 'id' in field.name
  }

LINKS.extend([(key, value['verbose_name']) for key, value in get_field_details(SupplierProduct).items() 
              if not value['primary_key']
              and not key == 'supplier'])

NECESSARY = ['supplier', 'article', 'name']

FOREIGN = [key for key, value in get_field_details(Product).items() if value['is_relation']]


def match_manufacturer(name: str)->Manufacturer:
  return ManufacturerDict.objects.all().filter(name__icontains=name)[0].manufacturer
