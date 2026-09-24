"""Правило «основного» значения по уровням поставщиков.

Общее для экспорта (export.py — основные цены и остаток на «Товарах») и для
себестоимости набора из комплектующих (set_costs.py): у компонента берётся
та же основная себестоимость, что стоит у него в выгрузке. Держать правило в
одном месте — единственный способ не дать двум цифрам про один товар
разойтись.

Уровни — Supplier.price_priority / stock_priority: меньше — выше, пусто —
общий нижний уровень, строки без поставщика — в самом конце.
"""


def is_zero(value) -> bool:
    return value is None or value == 0


def main_value(levels, pick):
    """Основное значение по уровням: pick (min или max) из ненулевых значений
    первого уровня, где они есть.

    levels — значения, сгруппированные по уровням, сверху вниз; уровень из
    одного значения — просто «первое ненулевое по порядку». Ноль и пусто
    пропускаются — у самого приоритетного поставщика ноль чаще значит «цены
    нет», чем «бесплатно», и тогда решает следующий уровень. Если ненулевого
    нет ни на одном уровне: 0, если хоть у кого-то 0 (остаток
    синхронизировался, товара нет), иначе пусто (ни у кого нет данных) — NULL
    и 0 в остатке разные вещи.
    """
    seen = False
    for level in levels:
        level = list(level)
        non_zero = [value for value in level if not is_zero(value)]
        if non_zero:
            return pick(non_zero)
        seen = seen or any(value is not None for value in level)
    return 0 if seen else None


def cost_key(cost):
    """Ключ сортировки по себестоимости: меньшая — раньше, ноль и пусто — в конце."""
    return (is_zero(cost), cost or 0)


def level_key(supplier, priority_field):
    """Место поставщика среди уровней: проранжированные по номеру, затем
    общий нижний уровень непроранжированных, затем строки без поставщика.
    Тот же порядок, что у export.supplier_levels."""
    if supplier is None:
        return (2, 0)
    level = getattr(supplier, priority_field)
    return (1, 0) if level is None else (0, level)


def main_row(main_products, attr, priority_field, pick):
    """Основное значение поля `attr` по строкам поставщиков одного товара —
    и строка, у которой оно взято.

    То же правило, что main_value над export.supplier_levels, только сразу по
    строкам MainProduct: первый уровень, где есть ненулевое значение, внутри
    него pick (min для цены, max для остатка). Несколько строк одного
    поставщика в export сворачиваются тем же pick, так что результат совпадает.
    Строки должны идти с select_related('supplier').

    Возвращает (значение, строка): (None, None) — данных нет ни у кого,
    (0, None) — у кого-то есть, но только нули.
    """
    levels = {}
    for main_product in main_products:
        levels.setdefault(level_key(main_product.supplier, priority_field), []).append(main_product)
    seen = False
    for key in sorted(levels):
        rows = [row for row in levels[key] if not is_zero(getattr(row, attr))]
        if rows:
            winner = pick(rows, key=lambda row: getattr(row, attr))
            return getattr(winner, attr), winner
        seen = seen or any(getattr(row, attr) is not None for row in levels[key])
    return (0 if seen else None), None
