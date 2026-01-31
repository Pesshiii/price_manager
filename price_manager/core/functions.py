import pandas as pd
from io import StringIO
from .models import *
from django.db import transaction
from supplier_manager.models import Manufacturer, Category, ManufacturerDict
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

# SP_FOREIGN = [key for key, value in get_field_details(SupplierProduct).items() 
#               if '_ptr' in key
#               or (value['is_relation'] and not key in ['category', 'manufacturer'])
#               ]
# MP_FOREIGN = [key for key, value in get_field_details(MainProduct).items() if '_ptr' in key]

NECESSARY = ['supplier', 'article', 'name']

# Проверить надо это или нет
NA_VALUES = ['nan', '', '—', None]


def match_manufacturer(name: str)->Manufacturer:
  return ManufacturerDict.objects.all().filter(name__icontains=name)[0].manufacturer


def extract_initial_from_post(post, prefix="form", data={}, length=None):
  rows = []
  if not length:
    total = int(post.get(f"{prefix}-TOTAL_FORMS", 0))
  else:
    total = length
  for i in range(total):
      rows.append({
          key:  post.get(f"{prefix}-{i}-{key}", value) for key, value in data.items()
      })
  return rows

# --- Хелперы для импорта Производителя и Категории ---


def resolve_manufacturer(name: str) -> Manufacturer | None:
    """
    Возвращает/создаёт Manufacturer по имени.
    Порядок: точное совпадение -> словарь ManufacturerDict -> создать.
    """
    if not name:
        return None
    clean = str(name).strip()
    m = Manufacturer.objects.filter(name__iexact=clean).first()
    if m:
        return m
    md = ManufacturerDict.objects.filter(name__iexact=clean).select_related('manufacturer').first()
    if md:
        return md.manufacturer
    m, _ = Manufacturer.objects.get_or_create(name=clean)
    return m

def get_or_create_category_by_path(path: str, delimiter: str = ">") -> Category | None:
    """
    Создаёт/находит категорию по строке 'A > B > C' (до 10 уровней).
    """
    if not path:
        return None
    parts = [p.strip() for p in str(path).split(delimiter) if p and str(p).strip()]
    parent = None
    node = None
    for level, name in enumerate(parts[:10]):
        node, _ = Category.objects.get_or_create(parent=parent, name=name)
        parent = node
        return node
        last, _ = Category.objects.get_or_create(parent=parent, name=name)
        parent = last
        return last