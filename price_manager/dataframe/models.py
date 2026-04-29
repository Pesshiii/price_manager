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
        verbose_name="Источник",
        encoder=json.DjangoJSONEncoder,
    )
    cols=models.JSONField(
        verbose_name="Столбцы",
        blank=True,
        encoder=json.DjangoJSONEncoder,
    )

    CONF_SCHEMA = {
        "type": "object",
        "properties": {
            "source": {
                "title":"Источник",
                "oneOf": [
                    {
                    "type": "object",
                    "title": "Файл",
                    "properties": {
                        "type":{"type":"string", "widget":"hidden", "const":"file"},
                        "path": {"type": "string", "title": "Путь к файлу"},
                        "sheet": {"type": "string", "title": "Лист"},
                        "header_row": {"type": "number", "title": "Ряд заголовка"}
                    }
                    },
                    {
                    "type": "object",
                    "title": "API",
                    "properties": {
                        "type":{"type":"string", "widget":"hidden", "const":"api"},
                        "endpoint": {"type": "string", "title": "Endpoint"},
                        "parser": {"type": "string", "title": "Парсер/API метод"}
                    }
                    },
                    {
                    "type": "object",
                    "title": "БД",
                    "properties": {
                        "type":{"type":"string", "widget":"hidden", "const":"db"},
                        "dsn": {"type": "string", "title": "DSN"},
                        "query": {"type": "string", "title": "SQL/правило экспорта"}
                    }
                    }
                ]
            }
        }
    }
