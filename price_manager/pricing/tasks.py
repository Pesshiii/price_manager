import logging

from celery import shared_task
from django.db import transaction

from . import engine

logger = logging.getLogger(__name__)


@shared_task
def apply_feed_pricing(feed_id: int) -> None:
    """Thin adapter called when a ``SupplierFeed`` transitions to ``done``.

    Loads the feed and runs the three pricing-engine phases in a single
    transaction: extract raw prices, reconcile stock, apply rules. All the
    logic lives in ``pricing.engine``; this task only owns orchestration and
    the transaction boundary.
    """
    from supplier_feed.models import SupplierFeed

    try:
        feed = SupplierFeed.objects.select_related('supplier', 'feed_mapping').get(pk=feed_id)
    except SupplierFeed.DoesNotExist:
        return

    with transaction.atomic():
        skipped = engine.apply_raw_prices(feed)
        engine.reconcile_stock(feed)
        engine.apply_rules(feed.supplier)

    if skipped:
        logger.info('apply_feed_pricing feed=%s skipped %d unparseable price cell(s)', feed_id, skipped)
