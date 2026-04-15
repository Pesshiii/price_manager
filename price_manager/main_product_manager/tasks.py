from celery import chain, shared_task

from core.models import PersistentNotification
from core.task_runner import execute_locked_task
from django.contrib.auth import get_user_model
from supplier_manager.models import Category
from product_price_manager.models import update_prices

from .functions import recalculate_search_vectors, update_logs, update_stocks
from .models import MainProduct


def _build_step_result(payload: dict | None) -> dict:
    if payload is None:
        return {"status": "success", "updated_count": 0, "duration_ms": 0}
    return {
        "status": payload.get("status", "success"),
        "updated_count": int(payload.get("updated_count", 0) or 0),
        "duration_ms": int(payload.get("duration_ms", 0) or 0),
    }


def _append_step(stats: dict | None, step_name: str, payload: dict | None) -> dict:
    next_stats = dict(stats or {})
    steps = dict(next_stats.get("steps") or {})
    steps[step_name] = _build_step_result(payload)
    next_stats["steps"] = steps
    return next_stats


@shared_task(name="main_product_manager.rebuild_categories")
def rebuild_categories_task(stats: dict | None = None) -> dict:
    payload = execute_locked_task(
        task_name="main_product_manager.rebuild_categories",
        lock_ttl=60 * 10,
        runner=Category.objects.rebuild,
    )
    return _append_step(stats, "rebuild_categories", payload)


@shared_task(name="main_product_manager.recalculate_vectors_missing")
def recalculate_vectors_missing_task(stats: dict | None = None) -> dict:
    def _runner():
        queryset = MainProduct.objects.filter(search_vector__isnull=True)
        return recalculate_search_vectors(queryset) or 0

    payload = execute_locked_task(
        task_name="main_product_manager.recalculate_vectors_missing",
        lock_ttl=60 * 20,
        runner=_runner,
    )
    return _append_step(stats, "recalculate_vectors_missing", payload)


@shared_task(name="main_product_manager.update_prices")
def update_prices_task(stats: dict | None = None) -> dict:
    payload = execute_locked_task(
        task_name="main_product_manager.update_prices",
        lock_ttl=60 * 30,
        runner=update_prices,
    )
    return _append_step(stats, "update_prices", payload)


@shared_task(name="main_product_manager.update_stocks")
def update_stocks_task(stats: dict | None = None) -> dict:
    payload = execute_locked_task(
        task_name="main_product_manager.update_stocks",
        lock_ttl=60 * 15,
        runner=update_stocks,
    )
    return _append_step(stats, "update_stocks", payload)


@shared_task(name="main_product_manager.update_logs")
def update_logs_task() -> dict:
    return execute_locked_task(
        task_name="main_product_manager.update_logs",
        lock_ttl=60 * 20,
        runner=update_logs,
    )


@shared_task(name="main_product_manager.notify_sync_main_products")
def notify_sync_main_products_task(stats: dict, user_id: int) -> dict:
    steps = stats.get("steps", {})
    total_updated = sum(step.get("updated_count", 0) for step in steps.values())
    total_duration = sum(step.get("duration_ms", 0) for step in steps.values())
    has_errors = any(step.get("status") == "error" for step in steps.values())
    has_skipped = any(step.get("status") == "skipped" for step in steps.values())

    lines = [
        "Синхронизация главных товаров завершена.",
        f"Шагов выполнено: {len(steps)}.",
        f"Обновлено записей: {total_updated}.",
        f"Длительность: {round(total_duration / 1000, 2)} сек.",
        "",
        "Детали:",
    ]
    for name, step in steps.items():
        lines.append(
            f"• {name}: статус={step.get('status')}, "
            f"updated={step.get('updated_count', 0)}, "
            f"duration={round(step.get('duration_ms', 0) / 1000, 2)} сек."
        )

    level = "success"
    if has_errors:
        level = "danger"
    elif has_skipped:
        level = "warning"

    if get_user_model().objects.filter(pk=user_id).exists():
        PersistentNotification.objects.create(
            user_id=user_id,
            level=level,
            message="\n".join(lines),
        )

    return {
        "status": "ok",
        "level": level,
        "total_updated": total_updated,
        "total_duration_ms": total_duration,
        "steps": steps,
    }


def sync_main_products_task(user_id: int):
    workflow = chain(
        rebuild_categories_task.s(),
        recalculate_vectors_missing_task.s(),
        update_prices_task.s(),
        update_stocks_task.s(),
        notify_sync_main_products_task.s(user_id=user_id),
    )
    return workflow.apply_async()
