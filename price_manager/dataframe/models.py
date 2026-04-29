from django.db import models
from django.core.serializers import json
from django.core.validators import FileExtensionValidator
from core.models import SlugModel


from core.models import TimeStampedModel

# Create your models here.


class FileModel(models.Model):
    file = models.FileField(
        verbose_name='Файл',
        validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm', 'csv'])],
        null=False,
        upload_to='dataframe/'
    )


def _get_slug(item):
    return 

class Dataframe(TimeStampedModel, SlugModel):
    '''
    `name`:\\
        Если датафрейм создается из файла найвание генерируется автоматически\\
    `conf`:\\
        содержит информацию о том откуда берется дата (путь к файлу, в дальнейшем вызов API и парсинга, экспорт из бд)
        для файла указывается название листа и дополнительные настройки (пр. ряд хэдэра)
    'cols':
        настройки для изменения столбцов датафрэйма(пр. замены начений, применение функции, переименование)
    '''
    conf=models.JSONField(
        verbose_name="Настройка",
        encoder=json.DjangoJSONEncoder,
    )
    cols=models.JSONField(
        verbose_name="Столбцы",
        encoder=json.DjangoJSONEncoder,
    )
