"""Проверка импорта прайса перед применением.

Новый файл сравнивается с историей этой же настройки (ImportRun), а не с числом
товаров поставщика: у поставщика бывает несколько настроек, и общее число его
товаров включает строки чужих настроек. Цены и остатки проверяются раздельно —
столбец остатка может отвалиться, пока цены грузятся как обычно.

Отдельно, без истории, проверяется, сколько строк, привязанных к ГП, импорт
обнулит: покрытие этого не видит — поставщик, переименовавший товары, даёт
столько же строк, а все привязанные уходят в «нет в файле».
"""
from dataclasses import dataclass, field
from statistics import median

from django.conf import settings

from .models import ImportRun, Setting

GUARDED_METRICS = ("covered_price", "covered_stock")


@dataclass
class GuardVerdict:
    ok: bool
    # JSON-serialisable, stored on ImportRun.guard_reasons and rendered by
    # ImportRun.reason_lines().
    reasons: list = field(default_factory=list)


def evaluate(setting: Setting, stats: dict, exclude_pk: int | None = None) -> GuardVerdict:
    reasons = _coverage_reasons(setting, stats, exclude_pk)
    missing_linked = _missing_linked_reason(setting, stats)
    if missing_linked:
        reasons.append(missing_linked)
    return GuardVerdict(ok=not reasons, reasons=reasons)


def _coverage_reasons(setting: Setting, stats: dict, exclude_pk: int | None) -> list:
    ratio = settings.SUPPLIER_IMPORT_GUARD_RATIO
    window = settings.SUPPLIER_IMPORT_GUARD_WINDOW
    min_history = settings.SUPPLIER_IMPORT_GUARD_MIN_HISTORY

    # Confirmed imports are applied imports too: once a supplier genuinely
    # shrinks its price list, the median follows after a few confirmations.
    history = list(
        ImportRun.objects.filter(setting=setting, status=ImportRun.STATUS_APPLIED)
        .exclude(pk=exclude_pk)
        .order_by("-started_at")
        .values(*GUARDED_METRICS)[:window]
    )
    if len(history) < min_history:
        return [{"kind": "history", "have": len(history), "need": min_history}]

    reasons = []
    for metric in GUARDED_METRICS:
        values = [run[metric] for run in history if run[metric] is not None]
        if not values:
            continue
        baseline = median(values)
        # A metric the setting never delivered (median 0) has nothing to drop from.
        if baseline and stats.get(metric, 0) < ratio * baseline:
            reasons.append({
                "kind": "drop", "metric": metric,
                "value": stats.get(metric, 0), "baseline": round(baseline),
            })
    return reasons


def _missing_linked_reason(setting: Setting, stats: dict) -> dict | None:
    """Импорт обнулит остаток и цены у заметной доли строк настройки, привязанных к ГП."""
    # A setting that maps no stock or price clears nothing on missing rows.
    if not setting.clearable_fields():
        return None
    missing = stats.get("missing_linked") or 0
    linked = stats.get("linked_own") or 0
    threshold = max(settings.SUPPLIER_IMPORT_GUARD_MISSING_LINKED_MIN,
                    settings.SUPPLIER_IMPORT_GUARD_MISSING_LINKED_SHARE * linked)
    if missing and missing >= threshold:
        return {"kind": "missing_linked", "value": missing, "linked": linked}
    return None
