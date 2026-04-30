from django.db import models
from django.core.serializers import json
from django.core.validators import FileExtensionValidator
from django.core.files.base import ContentFile
from urllib.parse import urlparse
from pathlib import Path
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
        verbose_name="",
        encoder=json.DjangoJSONEncoder,
    )
    cols=models.JSONField(
        verbose_name="",
        blank=True,
        encoder=json.DjangoJSONEncoder,
    )



    def get_file_source(self):
        source = (self.conf or {}).get("source", {})
        file_url = source.get("file")
        if source.get("type") != "file" or not file_url:
            return None

        parsed = urlparse(file_url)
        source_path = parsed.path if parsed.scheme else file_url

        return FileModel.objects.filter(file=source_path.lstrip("/")).first()

    def set_file_source(self, file_obj: FileModel, sheet: str = "", header_row: int = 0):
        conf = self.conf or {}
        conf["source"] = {
            "type": "file",
            "file": file_obj.file.url if file_obj and file_obj.file else "",
            "sheet": sheet,
            "header_row": header_row,
        }
        self.conf = conf

    @classmethod
    def create_file_model_from_url(cls, file_url: str):
        parsed = urlparse(file_url)
        source_path = parsed.path if parsed.scheme else file_url
        filename = Path(source_path).name

        with open(source_path, "rb") as src:
            content = ContentFile(src.read(), name=filename)

        file_model = FileModel()
        file_model.file.save(filename, content, save=True)
        return file_model

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
                        "file": {"type": "string", "title": "Файл", "format": "file-url"},
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

    COL_SCHEMA={
        "type": "object",
        "keys": {
          "column":{
            "title":"Столбец",
            "type": "string",
            "choices": [
            ]
          },
          "link":{
                "title":"Связь",
                "type": "string",
                "widget": "autocomplete",
                "handler": "contentfield"
          },
          "default": {
              "title":"Пустая строка",
              "type": "string"
              },
          "dict": {
            "type": "array",
            "title": "Замены",
            "items": {
            "type": "object",
                "keys": {
                "key": {
                    "title":"Если",
                    "type": "string"
                },
                "value": {
                    "title":"То",
                    "type": "integer"
                }
                }
            },
            "minItems": 1,
            "maxItems": 5
            }
        }
    }
    
    COLS_SCHEMA={
        "type": "array",    
        "title": "Столбцы",
        "items": COL_SCHEMA,
        "minItems": 1,
        "maxItems": 5
    }
