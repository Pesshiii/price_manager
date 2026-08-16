from celery import shared_task
from django.utils import timezone
from price_manager.core.utils import update_cart_items

@shared_task(name="core.update_cart_items")
def update_cart_items_task(shopping_tab_id: int) -> dict:

    start_time = timezone.now()
    updated_count = update_cart_items(shopping_tab_id)
    duration_ms = (timezone.now() - start_time).total_seconds() * 1000

    return {
        "status": "success",
        "updated_count": updated_count,
        "duration_ms": duration_ms,
    }