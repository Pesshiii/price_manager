"""Строка прайса у строк ГП служебного поставщика «Без поставщика».

Остаток строки ГП поставщика update_stocks берёт из его прайса (SupplierProduct),
и строка без прайса получает 0. У служебного поставщика строки бывают и из
загруженного файла, и заведённые руками — возврат, бонус, остаток на складе. Чтобы
введённый руками остаток не обнулялся, у ручной строки тоже есть строка прайса,
и форма строки ГП держит её в согласии со строкой: артикул, название, остаток.

Строку из файла форма меняет только в остатке — артикул и название ведёт
импорт, как у любого поставщика.
"""
from __future__ import annotations

from .models import SupplierProduct


def _free_name(supplier_id, article, name, exclude_pk=None) -> str:
    """Название, под которым (поставщик, артикул, название) ещё свободно."""
    taken = SupplierProduct.objects.filter(supplier_id=supplier_id, article=article)
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)
    taken = set(taken.values_list('name', flat=True))
    candidate, n = name, 2
    while candidate in taken:
        candidate = f'{name} #{n}'
        n += 1
    return candidate


def sync_unsupplied_price_row(main_product) -> SupplierProduct | None:
    """Строка прайса строки ГП «Без поставщика» — создать или обновить.

    Строку перевели к другому поставщику — её ручная строка прайса «Без
    поставщика» удаляется (иначе осталась бы чужой). Прайс настоящих
    поставщиков не трогает — он только из файла.
    """
    supplier = main_product.supplier
    row = (SupplierProduct.objects.filter(main_product=main_product)
           .select_related('supplier').first())
    if supplier is None or not supplier.is_unsupplied:
        if (row is not None and row.supplier.is_unsupplied and row.supplier_id != main_product.supplier_id
                and not row.source_settings.exists()):
            row.delete()
        return None
    article = main_product.article or main_product.sku
    name = main_product.name or main_product.sku or article
    if row is None:
        row = SupplierProduct(supplier=supplier, main_product=main_product, article=article,
                              name=_free_name(supplier.pk, article, name))
    elif not row.source_settings.exists():
        row.article = article
        row.name = _free_name(supplier.pk, article, name, exclude_pk=row.pk)
    row.stock = main_product.stock
    row.save()
    return row
