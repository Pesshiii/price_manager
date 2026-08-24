from celery import chain, shared_task

from core.task_runner import execute_locked_task

from .models import Category


@shared_task(name="supplier_manager.recalculate_category_vectors_missing")
def recalculate_category_vectors_missing_task(stats: dict | None = None) -> dict:
    def _runner():
        queryset = Category.objects.filter(search_vector__isnull=True)
        count = 0
        for cat in queryset.iterator():
            cat.rebuild_search_vector()
            count += 1
        return count

    return execute_locked_task(
        task_name="supplier_manager.recalculate_category_vectors_missing",
        lock_ttl=60 * 10,
        runner=_runner,
    )


@shared_task(name="supplier_manager.sync_categories")
def sync_categories_task():
    from main_product_manager.tasks import rebuild_categories_task

    workflow = chain(
        rebuild_categories_task.s(),
        recalculate_category_vectors_missing_task.s(),
    )
    return workflow.apply_async()
