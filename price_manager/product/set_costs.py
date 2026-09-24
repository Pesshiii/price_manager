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

Считается только для строк страницы (или партии выгрузки), двумя запросами на
всю партию — не на строку.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count

from main_product_manager.models import MainProduct

from .main_values import is_zero, main_row
from .models import ProductSetItem


@dataclass
class SetLine:
    item: ProductSetItem
    amount: int
    cost: Decimal | None = None          # основная себестоимость одной штуки
    cost_row: MainProduct | None = None  # строка поставщика, откуда она взята
    stock: int | None = None             # основной остаток компонента
    buildable: int | None = None         # сколько наборов хватит этого компонента
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
            line.stock, _ = main_row(component_rows, 'stock', 'stock_priority', max)
            if line.stock is not None:
                line.buildable = max(line.stock, 0) // line.amount
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
