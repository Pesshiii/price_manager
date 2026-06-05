from celery import shared_task
from django.core.cache import cache

from supplier_feed.models import SupplierFeed, SupplierFeedEntry
from transform.engine import apply_rules
from transform.models import ProductSnapshot

_LOCK_TTL = 3600


@shared_task
def run_transform_task(feed_id: int) -> None:
    lock_key = f'transform:{feed_id}'
    if not cache.add(lock_key, '1', timeout=_LOCK_TTL):
        return

    try:
        try:
            feed = SupplierFeed.objects.select_related('feed_mapping__supplier').get(pk=feed_id)
        except SupplierFeed.DoesNotExist:
            return

        for entry in SupplierFeedEntry.objects.filter(
            feed=feed, product__isnull=False
        ).select_related('product', 'feed__feed_mapping__supplier'):
            data_dict = apply_rules(feed.feed_mapping, entry, entry.product)
            ProductSnapshot.objects.update_or_create(
                product=entry.product,
                supplier=feed.feed_mapping.supplier,
                defaults={'data': data_dict, 'source_feed': feed},
            )
    finally:
        cache.delete(lock_key)
