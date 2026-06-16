"""Single owner of the SupplierFeed `partial → done` completion transition.

The transition has two callers — the matching task (`tasks.py`) and the
MatchQueue viewset actions (`api/views.py`). Both must: take a per-feed row
lock, guard against a double-DONE, check that the MatchQueue is empty, write
`status=done`, and schedule pricing on commit. Keeping that logic here means
the lock + guard can never drift between the two paths.
"""
from __future__ import annotations

from django.db import transaction

from .models import STATUS_DONE, SupplierFeed, SupplierFeedEntry


def queue_is_empty(feed_pk: int) -> bool:
    """True when no entry of this feed is still awaiting a manual decision.

    The MatchQueue is the filter ``product IS NULL AND skipped = False``;
    an empty queue is the gate for the `partial → done` transition.
    """
    return not SupplierFeedEntry.objects.filter(
        feed_id=feed_pk, product__isnull=True, skipped=False
    ).exists()


def complete_feed(feed: SupplierFeed) -> bool:
    """Transition ``feed`` to DONE and trigger pricing iff its queue is empty.

    Concurrency-safe and idempotent: re-reads the feed under
    ``select_for_update`` inside its own transaction, no-ops when the feed is
    already DONE or the queue is not yet empty.

    Returns ``True`` only when this call performed the transition, so callers
    can distinguish "completed now" from "still has work" (e.g. the matcher
    falling back to ``partial``). On success the passed-in ``feed`` instance is
    mutated in place to reflect the new state.
    """
    from pricing.tasks import apply_feed_pricing

    with transaction.atomic():
        locked = SupplierFeed.objects.select_for_update().get(pk=feed.pk)
        if locked.status == STATUS_DONE:
            return False
        if not queue_is_empty(locked.pk):
            return False

        locked.status = STATUS_DONE
        locked.error = ''
        locked.save(update_fields=['status', 'error'])
        transaction.on_commit(lambda: apply_feed_pricing.delay(locked.pk))

    feed.status = STATUS_DONE
    feed.error = ''
    return True
