from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout
from django import forms
from django_jsonform.forms.fields import JSONFormField

from .models import Dataframe


CONF_SCHEMA = {
    "type": "object",
    "title": "Конфигурация источника данных",
    "properties": {
        "source_type": {
            "type": "string",
            "title": "Источник данных",
            "enum": ["file", "api", "db"],
        },
        "source": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "object",
                    "title": "Файл",
                    "properties": {
                        "path": {"type": "string", "title": "Путь к файлу"},
                        "sheet": {"type": "string", "title": "Лист"},
                        "header_row": {"type": "number", "title": "Ряд заголовка"},
                        "options": {"type": "object", "title": "Доп. настройки"},
                    },
                },
                "api": {
                    "type": "object",
                    "title": "API",
                    "properties": {
                        "endpoint": {"type": "string", "title": "Endpoint"},
                        "parser": {"type": "string", "title": "Парсер/API метод"},
                    },
                },
                "db": {
                    "type": "object",
                    "title": "БД",
                    "properties": {
                        "dsn": {"type": "string", "title": "DSN"},
                        "query": {"type": "string", "title": "SQL/правило экспорта"},
                    },
                },
            },
        },
    },
}


class ConfForm(forms.Form):
    conf = JSONFormField(label="Настройка", schema=CONF_SCHEMA)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_tag = False
        self.helper.layout = Layout(Field("conf"))


class Form(forms.ModelForm):
    conf = JSONFormField(label="Настройка", schema=CONF_SCHEMA)

    class Meta:
        model = Dataframe
        fields = ["name", "conf", "cols"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "cols": forms.Textarea(attrs={"class": "form-control", "rows": 8}),
        }
