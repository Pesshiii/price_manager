from django.db import models
from django.core.validators import FileExtensionValidator

# Обработка файлов

class FileModel(models.Model):
  file = models.FileField(verbose_name='Файл',
                         validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm'])],
                         null=False)