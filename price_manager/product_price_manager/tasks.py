from celery import shared_task

from core.task_runner import execute_locked_task
from main_product_manager.functions import update_logs, update_stocks

from .models import update_prices


@shared_task(name="product_price_manager.update_prices")
def update_prices_task() -> dict:
    return execute_locked_task(
        task_name="product_price_manager.update_prices",
        lock_ttl=60 * 30,
        runner=update_prices,
    )


@shared_task(name="product_price_manager.update_stocks")
def update_stocks_task() -> dict:
    return execute_locked_task(
        task_name="product_price_manager.update_stocks",
        lock_ttl=60 * 15,
        runner=update_stocks,
    )


@shared_task(name="product_price_manager.update_logs")
def update_logs_task() -> dict:
    return execute_locked_task(
        task_name="product_price_manager.update_logs",
        lock_ttl=60 * 20,
        runner=update_logs,
    )
