from celery import shared_task


@shared_task
def apply_feed_pricing(feed_id: int) -> None:
    pass  # Full implementation in pricing app PR
