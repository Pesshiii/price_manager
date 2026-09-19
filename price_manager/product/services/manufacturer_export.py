"""Выгрузка производителей от поставщиков для обогащения PIM (P2-G4).

Зачем. D1 закрывает разрыв в брендах обогащением PIM, а Phase 2 удаляет
SupplierProduct.manufacturer. Для ~62% товаров этот столбец — единственная
информация о бренде, которая вообще есть. Эта выгрузка переносит её к тем, кто
обогащает PIM, ДО удаления. См. §0.5 и P2-G4 в .claude/shift-to-product-brief.md.

Источник — SupplierProduct.manufacturer, а НЕ MainProduct.manufacturer.
sync_pim_relations перезаписывает MainProduct.manufacturer брендом PIM, так что
для связанных товаров там отчасти сам PIM, а выгружать его обратно в PIM
бессмысленно. Сырой столбец пишет только импорт Excel.

Строка — пара (товар, производитель). Если поставщики одного товара называют
разных производителей, товар даёт несколько строк с флагом «поставщики
расходятся»: человек, который будет разбирать бренд, должен видеть спор, а не
результат монетки. Написания, отличающиеся только регистром и пробелами по
краям, спором не считаются.

Жизненный цикл: команда читает поле, которое Phase 2 удаляет, поэтому Phase 2
обязан удалить и её.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from supplier_product_manager.models import SupplierProduct

from ..models import Product

STATUS_NO_BRAND = 'нет бренда в PIM'
STATUS_DISAGREES = 'расходится с брендом PIM'

HEADER = [
    'Номер',
    'Название',
    'Производитель (от поставщиков)',
    'Поставщики расходятся',
    'Бренд в PIM',
    'Статус',
]


@dataclass
class ExportResult:
    rows: list[list[str]] = field(default_factory=list)
    products: int = 0
    products_with_conflict: int = 0
    # Товары с брендом в PIM, которые не попали в выгрузку: по умолчанию —
    # все такие, с include_disagreements — только те, где поставщик бренд
    # подтверждает.
    skipped_with_pim_brand: int = 0
    unlinked_supplier_rows: int = 0


def _key(name: str) -> str:
    return name.strip().casefold()


def build_manufacturer_export(include_disagreements: bool = False) -> ExportResult:
    """Собирает строки выгрузки.

    По умолчанию — ровно то, что требует P2-G4: товары БЕЗ бренда в PIM, у
    которых есть производитель от поставщика. Товары без того и другого не
    попадают: выгружать про них нечего.

    include_disagreements добавляет товары, у которых бренд в PIM есть, но ни
    один поставщик его не подтверждает. Бриф просит команду PIM проверить их
    отдельно: почти все такие расхождения — один бренд PIM против разных
    производителей у поставщиков.

    Товар без бренда в PIM определяется по Product.brand, а тот заполняет
    бэкфилл из PIM. Если бэкфилл ещё не прошёл, «без бренда» окажутся все
    товары и выгрузка выйдет шире нужного. Это безопасная сторона ошибки:
    ничего не теряется, просто лишние строки.
    """
    result = ExportResult()

    manufacturers: dict[int, dict[str, str]] = defaultdict(dict)
    fallback_name: dict[int, str] = {}
    supplier_rows = (
        SupplierProduct.objects
        .filter(manufacturer__isnull=False)
        .values_list('main_product__product_id', 'manufacturer__name', 'main_product__name')
        .order_by('main_product__product_id', 'pk')
    )
    for product_id, manufacturer, main_product_name in supplier_rows.iterator(chunk_size=5000):
        if product_id is None:
            # Строка прайса, которая не дошла до каталога. Её производитель
            # Phase 2 тоже удалит, но обогащать в PIM нечего — у неё нет
            # товара. Считаем, чтобы это было видно, а не молча.
            result.unlinked_supplier_rows += 1
            continue
        if not (manufacturer or '').strip():
            continue
        manufacturers[product_id].setdefault(_key(manufacturer), manufacturer.strip())
        if main_product_name and product_id not in fallback_name:
            fallback_name[product_id] = main_product_name

    # Полный проход с проверкой по словарю, а не pk__in: на проде в словаре
    # ~118 тыс. id, и IN такой длины обходится дороже, чем просто пройти
    # 155 тыс. строк.
    products = (
        Product.objects
        .values_list('pk', 'number', 'name', 'brand__name')
        .order_by('number', 'pk')
    )
    for pk, number, name, brand in products.iterator(chunk_size=5000):
        found = manufacturers.get(pk)
        if not found:
            continue
        if brand:
            if not include_disagreements or _key(brand) in found:
                result.skipped_with_pim_brand += 1
                continue
            status = STATUS_DISAGREES
        else:
            status = STATUS_NO_BRAND

        conflict = len(found) > 1
        result.products += 1
        result.products_with_conflict += conflict
        # display_name, но без запроса на каждую строку: имя из PIM, иначе
        # название от поставщика, иначе номер.
        display = name or fallback_name.get(pk) or number or ''
        for spelling in sorted(found.values(), key=str.casefold):
            result.rows.append([
                number or '',
                display,
                spelling,
                'да' if conflict else '',
                brand or '',
                status,
            ])
    return result
