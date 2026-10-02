"""Себестоимость и остаток набора «из комплектующих».

Считается по составу (ProductSetItem) рядом с собственными строками набора —
собранный на складе набор со своей ценой остаётся обычными строками
поставщиков, а это вторая цифра: во сколько он обойдётся, если собрать.

У каждого компонента берутся основная себестоимость и основной остаток по
уровням поставщиков — те же, что у него в выгрузке (main_values.main_row).
Себестоимость набора — сумма «количество × себестоимость» по компонентам,
у которых она есть; сколько можно собрать — минимум «остаток // количество».
Компонент без цены или без данных об остатке в сумму и минимум не входит,
но считается: неполный набор показывается с пометкой, а не выдаётся за полный.

Срок поставки компонента — срок поставщика той строки, откуда взят его
основной остаток (у строки набора — её собственный срок, вложенный набор);
срок набора — самый долгий по составу.

Считается только для строк страницы (или партии выгрузки), двумя запросами на
всю партию — не на строку.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count

from main_product_manager.models import MainProduct

from .main_values import is_zero, level_key, main_row
from .models import ProductSetItem


@dataclass
class SetLine:
    item: ProductSetItem
    amount: int
    cost: Decimal | None = None          # основная себестоимость одной штуки
    cost_row: MainProduct | None = None  # строка поставщика, откуда она взята
    stock: int | None = None             # основной остаток компонента
    buildable: int | None = None         # сколько наборов хватит этого компонента
    delivery_days: int | None = None     # срок поставщика основного остатка
    limiting: bool = False

    @property
    def component(self):
        return self.item.component

    @property
    def has_cost(self) -> bool:
        return not is_zero(self.cost)

    @property
    def line_cost(self) -> Decimal | None:
        return self.cost * self.amount if self.has_cost else None


@dataclass
class SetTotals:
    lines: list[SetLine] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.lines)

    @property
    def cost(self) -> Decimal | None:
        """Сумма по компонентам с ценой. None — цены нет ни у одного."""
        costs = [line.line_cost for line in self.lines if line.has_cost]
        return sum(costs, Decimal('0')) if costs else None

    @property
    def missing_cost(self) -> int:
        """Сколько компонентов без цены: нет в Price Manager или у всех поставщиков ноль."""
        return sum(not line.has_cost for line in self.lines)

    @property
    def buildable(self) -> int | None:
        """Сколько наборов можно собрать. None — ни у одного компонента нет данных."""
        known = [line.buildable for line in self.lines if line.buildable is not None]
        return min(known) if known else None

    @property
    def missing_stock(self) -> int:
        return sum(line.buildable is None for line in self.lines)

    @property
    def stock(self) -> int | None:
        """Остаток строки набора: сколько можно собрать — только если остаток
        известен у всех компонентов, иначе пусто (как и себестоимость)."""
        return self.buildable if self.count and not self.missing_stock else None

    @property
    def delivery_days(self) -> int | None:
        """Срок набора — самый долгий по компонентам. Пусто, если хоть у одного
        срок неизвестен: без него самый долгий может оказаться не тем."""
        days = [line.delivery_days for line in self.lines]
        return max(days) if days and None not in days else None


def stock_source_row(component_rows, value, winner):
    """Строка, чей срок поставки — срок компонента.

    Обычно — строка основного остатка (main_row). Если у всех только нули,
    победителя нет — тогда первая строка с данными на самом высоком уровне по
    остаткам: товара нет нигде, и срок — «при отсутствии» у того поставщика,
    которому верят первым.
    """
    if winner is not None or value is None:
        return winner
    known = [row for row in component_rows if row.stock is not None]
    return min(known, key=lambda row: (level_key(row.supplier, 'stock_priority'), row.pk))


def set_totals_for(product_pks) -> dict[int, SetTotals]:
    """{pk набора: SetTotals} для тех из product_pks, у кого есть состав."""
    items = list(ProductSetItem.objects.filter(set_product_id__in=list(product_pks))
                 .select_related('component').order_by('set_product_id', 'sorting', 'pk'))
    if not items:
        return {}

    rows = defaultdict(list)
    component_pks = {item.component_id for item in items if item.component_id}
    for main_product in (MainProduct.objects.filter(product_id__in=component_pks)
                         .select_related('supplier').order_by('pk')):
        rows[main_product.product_id].append(main_product)

    totals = defaultdict(SetTotals)
    for item in items:
        line = SetLine(item=item, amount=item.amount)
        component_rows = rows.get(item.component_id, [])
        if component_rows:
            line.cost, line.cost_row = main_row(component_rows, 'prime_cost', 'price_priority', min)
            line.stock, stock_row = main_row(component_rows, 'stock', 'stock_priority', max)
            if line.stock is not None:
                line.buildable = max(line.stock, 0) // line.amount
                line.delivery_days = stock_source_row(component_rows, line.stock, stock_row).get_delivery_days()
        totals[item.set_product_id].lines.append(line)

    for set_totals in totals.values():
        buildable = set_totals.buildable
        if buildable is not None:
            for line in set_totals.lines:
                line.limiting = line.buildable == buildable
    return dict(totals)


def attach_set_info(products) -> None:
    """Навешивает на товары страницы set_totals (если это набор) и
    in_sets_count (в скольких наборах он компонент). Три запроса на страницу.

    Атрибутами на экземпляры, а не аннотациями в выборку: считать это по всем
    158 тыс. строкам ради 25 показанных незачем, а агрегат по составу в
    GROUP BY основной выборки тянул бы её за собой.
    """
    products = list(products)
    pks = [product.pk for product in products]
    totals = set_totals_for(pks)
    in_sets = dict(ProductSetItem.objects.filter(component_id__in=pks)
                   .values('component_id').annotate(n=Count('set_product_id', distinct=True))
                   .values_list('component_id', 'n'))
    for product in products:
        product.set_totals = totals.get(product.pk)
        product.in_sets_count = in_sets.get(product.pk, 0)
