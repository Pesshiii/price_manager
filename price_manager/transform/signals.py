from django.db.models.signals import post_save
from django.dispatch import receiver

from supplier_feed.models import STATUS_DONE, STATUS_MATCHED, SupplierFeed
from transform.tasks import run_transform_task


@receiver(post_save, sender=SupplierFeed)
def on_supplier_feed_saved(sender, instance, **kwargs):
    if instance.status in (STATUS_MATCHED, STATUS_DONE):
        run_transform_task.delay(instance.pk)
