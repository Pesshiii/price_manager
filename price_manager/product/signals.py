"""Re-index a Product's embedding whenever its indexable text changes.

Schedules :func:`product.tasks.embed_products_task` on ``transaction.on_commit``
so the task only fires for committed rows — never for rolled-back imports.
The task itself is hash-idempotent, so re-firing on irrelevant saves only
wastes a SELECT, not an Ollama call.
"""
from __future__ import annotations

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


@receiver(post_save, sender=Product)
def _enqueue_product_embedding(sender, instance, created, update_fields=None, **kwargs):
    if update_fields is not None:
        if not (_EMBED_TRIGGER_FIELDS & set(update_fields)):
            return

    # Import inside the handler to dodge import-time circular references and
    # to keep Django's app-loading step Celery-free.
    from .tasks import embed_products_task

    pk = instance.pk
    transaction.on_commit(lambda: embed_products_task.delay([pk]))
