"""Re-index a Product's embedding whenever its indexable text changes.

Schedules :func:`product.tasks.embed_products_task` on ``transaction.on_commit``
so the task only fires for committed rows — never for rolled-back imports.
The task itself is hash-idempotent, so re-firing on irrelevant saves only
wastes a SELECT, not an Ollama call.

During bulk imports we don't want N single-pk tasks to flood the queue —
``run_import_commit`` already enqueues chunked embed tasks for the whole
``affected_ids`` set. ``suppress_embedding_signal()`` is the opt-out hook
the importer wraps around its commit loop.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Product

# Fields whose change should retrigger embedding. ``image_urls``, ``status``,
# ``created_at`` / ``updated_at`` are deliberately excluded.
_EMBED_TRIGGER_FIELDS = {
    'name',
    'description',
    'category',
    'category_id',
    'brand',
    'brand_id',
    'characteristics',
}


# threading.local ties suppression to the current OS thread, which is correct
# for Celery's default prefork pool (one task per process/thread).
# WARNING: incompatible with gevent/eventlet pools (-P gevent / -P eventlet) —
# there, multiple coroutines share one thread, so suppression would bleed
# across concurrent tasks. If you ever switch to a green-thread pool, replace
# this with a contextvars.ContextVar instead.
_import_state = threading.local()


@contextmanager
def suppress_embedding_signal():
    """While active, ``post_save`` on Product does not enqueue an embed task.

    Use during bulk imports — the importer enqueues one chunked embed task per
    batch of affected ids after commit, which is strictly cheaper than the
    per-row signal path.
    """
    prev = getattr(_import_state, 'suppressed', False)
    _import_state.suppressed = True
    try:
        yield
    finally:
        _import_state.suppressed = prev


@receiver(post_save, sender=Product)
def _enqueue_product_embedding(sender, instance, created, update_fields=None, **kwargs):
    if getattr(_import_state, 'suppressed', False):
        return

    if update_fields is not None:
        if not (_EMBED_TRIGGER_FIELDS & set(update_fields)):
            return

    # Import inside the handler to dodge import-time circular references and
    # to keep Django's app-loading step Celery-free.
    from .tasks import embed_products_task

    pk = instance.pk
    transaction.on_commit(lambda: embed_products_task.delay([pk]))
