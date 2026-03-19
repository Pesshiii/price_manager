from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .functions import invalidate_setting_cache
from .models import Setting, SupplierFile


@receiver(post_save, sender=Setting)
def clear_setting_cache_on_setting_save(sender, instance: Setting, **kwargs):
    invalidate_setting_cache(instance.pk)


@receiver(post_save, sender=SupplierFile)
def clear_setting_cache_on_file_save(sender, instance: SupplierFile, **kwargs):
    if instance.setting_id:
        invalidate_setting_cache(instance.setting_id)


@receiver(post_delete, sender=SupplierFile)
def clear_setting_cache_on_file_delete(sender, instance: SupplierFile, **kwargs):
    if instance.setting_id:
        invalidate_setting_cache(instance.setting_id)
