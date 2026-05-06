from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.core.validators import FileExtensionValidator
import os


class FileModel(models.Model):
    file = models.FileField(
        verbose_name='Файл',
        validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm', 'csv'])],
        null=False,
        upload_to='dataframe/',
    )
    @property
    def filename(self):
        return os.path.basename(self.file.name).split('.')[0]

@receiver(pre_delete, sender=FileModel)
def document_pre_delete(sender, instance, **kwargs):
    """Clean up file before model deletion"""
    instance.file.delete(save=False)