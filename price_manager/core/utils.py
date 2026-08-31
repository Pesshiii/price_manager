import pandas as pd
from io import StringIO, BytesIO
from .models import *
from django.db import transaction
from django.core.files.base import ContentFile
from django.db.models import Case, When, Value, IntegerField
from django.http import QueryDict
from django.utils import timezone
from supplier_manager.models import Manufacturer, Category, ManufacturerDict
from .models import ShoppingTab, CartItem
from main_product_manager.models import MainProduct
from main_product_manager.filters import MainProductFilter
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

# Сколько кандидатов оставлять каждой позиции при массовом импорте.
# find_main_products отдаёт их по убыванию релевантности, поэтому это лучшие N.
CART_IMPORT_MAX_CANDIDATES = 20

CART_IMPORT_EXTENSIONS = ('.csv', '.xlsx', '.xls')


def read_shopping_tab_dataframe(shopping_tab: ShoppingTab) -> pd.DataFrame:
    """Читает прикреплённый к заявке файл в DataFrame."""
    if not shopping_tab.file:
        raise ValueError("Файл не найден")
    name = shopping_tab.file.name.lower()
    if name.endswith('.csv'):
        return pd.read_csv(shopping_tab.file.path, encoding='utf-8')
    if name.endswith(('.xlsx', '.xls')):
        return pd.read_excel(shopping_tab.file.path)
    raise ValueError("Неподдерживаемый формат файла")


def parse_cart_item_rows(
    df: pd.DataFrame,
    query_column: str,
    quantity_column: str | None = None,
) -> list[dict]:
    """Строки файла → [{'search_query': …, 'quantity': …}]. Пустые запросы пропускаются."""
    rows = []
    for _, row in df.iterrows():
        raw_query = row.get(query_column)
        if pd.isnull(raw_query):
            continue
        search_query = str(raw_query).strip()
        if not search_query:
            continue
        quantity = 1
        if quantity_column:
            try:
                quantity = int(float(row.get(quantity_column)))
            except (TypeError, ValueError):
                quantity = 1
            if quantity < 1:
                quantity = 1
        rows.append({'search_query': search_query, 'quantity': quantity})
    return rows


def update_cart_items(
    shopping_tab_id: int,
    query_column: str,
    quantity_column: str | None = None,
    max_candidates: int = CART_IMPORT_MAX_CANDIDATES,
) -> int:
    """Создаёт позиции заявки из прикреплённого файла. Возвращает количество созданных."""
    shopping_tab = ShoppingTab.objects.get(id=shopping_tab_id)
    df = read_shopping_tab_dataframe(shopping_tab)
    created_count = 0
    for row in parse_cart_item_rows(df, query_column, quantity_column):
        cart_item = CartItem.objects.create(
            user=shopping_tab.user,
            search_query=row['search_query'],
            quantity=row['quantity'],
        )
        candidates = find_main_products(row['search_query'])[:max_candidates]
        if candidates:
            cart_item.products.set(candidates)
        shopping_tab.items.add(cart_item)
        created_count += 1
    return created_count

def order_cart_items(queryset):
    """Неподтверждённые позиции — наверх: именно они требуют решения."""
    return queryset.annotate(
        needs_choice=Case(
            When(confirmed_product__isnull=True, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by('needs_choice', 'id')


SHOPPING_TAB_EXPORT_COLUMNS = [
    'Запрос',
    'Количество',
    'Статус',
    'Товар',
    'Артикул',
    'Поставщик',
    'Производитель',
    'Цена',
    'Сумма',
]


def build_shopping_tab_export(shopping_tab_id: int, user_id: int | None = None) -> ShoppingTabExport:
    """Собирает xlsx по позициям заявки и сохраняет его в ShoppingTabExport."""
    shopping_tab = ShoppingTab.objects.get(pk=shopping_tab_id)
    items = order_cart_items(
        shopping_tab.items
        .select_related(
            'confirmed_product',
            'confirmed_product__supplier',
            'confirmed_product__manufacturer',
        )
    )

    rows = []
    for item in items:
        product = item.confirmed_product
        rows.append({
            'Запрос': item.search_query or '',
            'Количество': item.quantity,
            'Статус': 'Подтверждён' if product else 'Требует выбора',
            'Товар': product.name if product else '',
            'Артикул': (product.sku or product.article) if product else '',
            'Поставщик': str(product.supplier) if product else '',
            'Производитель': str(product.manufacturer) if product and product.manufacturer else '',
            'Цена': item.confirmed_price,
            'Сумма': item.line_total,
        })

    df = pd.DataFrame(rows, columns=SHOPPING_TAB_EXPORT_COLUMNS)
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)

    export = ShoppingTabExport(
        tab=shopping_tab,
        user_id=user_id or shopping_tab.user_id,
        rows_count=len(rows),
    )
    # Имя на диске держим ASCII — красивое имя подставляется при скачивании.
    filename = f'shopping-tab-{shopping_tab.pk}-{timezone.now():%Y%m%d-%H%M%S}.xlsx'
    export.file.save(filename, ContentFile(buffer.read()), save=True)
    return export


def find_main_products(search_query: str|None) -> list[MainProduct]:
    """
    Находит все главные продукты, подходящие под поисковый запрос.
    Пустой запрос не совпадает ни с чем.
    """
    if not search_query or not search_query.strip():
        return []
    # MainProductFilter.config_filters читает data.getlist — нужен QueryDict, а не dict.
    data = QueryDict(mutable=True)
    data['search'] = search_query
    filter = MainProductFilter(data=data, queryset=MainProduct.objects.all())
    return list(filter.qs)