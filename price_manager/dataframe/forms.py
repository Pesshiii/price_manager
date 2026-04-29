from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Field, Layout

from .models import Dataframe


class ConfSourceForm(forms.Form):
    SOURCE_CHOICES = (
        ("file", "Файл"),
        ("api", "API"),
        ("db", "База данных"),
    )

    source_type = forms.ChoiceField(label="Источник данных", choices=SOURCE_CHOICES)
    file_path = forms.CharField(label="Путь к файлу", required=False)
    file_sheet = forms.CharField(label="Лист", required=False)
    file_header_row = forms.IntegerField(label="Ряд заголовков", required=False, min_value=0)
    file_options = forms.CharField(
        label="Доп. настройки файла (JSON)", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    api_endpoint = forms.URLField(label="API endpoint", required=False)
    api_parser = forms.CharField(label="Парсер/API метод", required=False)

    db_dsn = forms.CharField(label="DSN/подключение БД", required=False)
    db_query = forms.CharField(label="SQL/экспорт правило", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("source_type"),
            Div(
                Field("file_path"),
                Field("file_sheet"),
                Field("file_header_row"),
                Field("file_options"),
                css_class="mb-3",
            ),
            Div(
                Field("api_endpoint"),
                Field("api_parser"),
                css_class="mb-3",
            ),
            Div(
                Field("db_dsn"),
                Field("db_query"),
                css_class="mb-3",
            ),
        )


class Form(forms.ModelForm):
    class Meta:
        model = Dataframe
        fields = ["name", "conf", "cols"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "conf": forms.Textarea(attrs={"class": "form-control", "rows": 8, "readonly": "readonly"}),
            "cols": forms.Textarea(attrs={"class": "form-control", "rows": 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        conf = self.instance.conf if getattr(self.instance, "pk", None) else {}
        self.conf_source_form = ConfSourceForm(initial=self._conf_to_initial(conf))

    def _conf_to_initial(self, conf):
        source_type = conf.get("source_type", "file")
        source = conf.get("source", {})
        file_source = source.get("file", {})
        api_source = source.get("api", {})
        db_source = source.get("db", {})
        return {
            "source_type": source_type,
            "file_path": file_source.get("path", ""),
            "file_sheet": file_source.get("sheet", ""),
            "file_header_row": file_source.get("header_row"),
            "file_options": file_source.get("options", ""),
            "api_endpoint": api_source.get("endpoint", ""),
            "api_parser": api_source.get("parser", ""),
            "db_dsn": db_source.get("dsn", ""),
            "db_query": db_source.get("query", ""),
        }

    def clean(self):
        cleaned_data = super().clean()
        conf_source_form = ConfSourceForm(self.data)
        self.conf_source_form = conf_source_form
        if not conf_source_form.is_valid():
            for field, errors in conf_source_form.errors.items():
                for err in errors:
                    self.add_error("conf", f"{field}: {err}")
            return cleaned_data

        src = conf_source_form.cleaned_data
        source_type = src["source_type"]
        conf = {"source_type": source_type, "source": {}}

        conf["source"]["file"] = {
            "path": src.get("file_path"),
            "sheet": src.get("file_sheet"),
            "header_row": src.get("file_header_row"),
            "options": src.get("file_options"),
        }
        conf["source"]["api"] = {
            "endpoint": src.get("api_endpoint"),
            "parser": src.get("api_parser"),
        }
        conf["source"]["db"] = {
            "dsn": src.get("db_dsn"),
            "query": src.get("db_query"),
        }

        cleaned_data["conf"] = conf
        return cleaned_data
