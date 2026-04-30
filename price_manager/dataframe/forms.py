from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout, Submit, HTML
from django import forms
from django_jsonform.forms.fields import JSONFormField
from django.urls import reverse
import pandas as pd
from urllib.parse import urlparse

from .models import Dataframe, FileModel


class Form(forms.ModelForm):
    conf = JSONFormField(label="Настройка", schema=Dataframe.CONF_SCHEMA)
    cols = JSONFormField(label="Столбцы", schema=Dataframe.COLS_SCHEMA)

    class Meta:
        model = Dataframe
        fields = ["name", "conf", "cols"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hydrate_dynamic_schemas()
        self.helper = FormHelper(self)

        self.helper.attrs = {
            "hx-post": reverse("dataframe:create") if not self.instance.pk else reverse("dataframe:update", kwargs={"slug": self.instance.slug}),
            "hx-trigger": "change delay:300ms, submit",
            "hx-push-url": "false",
        }
        self.helper.layout = Layout(
            Field('name'),
            Field('conf'),
            Field('cols'),
            Submit(name='save', value="Сохранить")
        )

    def _hydrate_dynamic_schemas(self):
        file_obj = None
        conf = self.initial.get("conf") or getattr(self.instance, "conf", None) or {}
        source = conf.get("source", {}) if isinstance(conf, dict) else {}
        file_url = source.get("file")
        if source.get("type") == "file" and file_url:
            parsed = urlparse(file_url)
            source_path = parsed.path if parsed.scheme else file_url
            file_obj = FileModel.objects.filter(file=source_path.lstrip("/")).first()

        if not file_obj:
            return

        sheets = self._get_sheet_names(file_obj.file.path)
        columns = self._get_columns(file_obj.file.path, sheets[0] if sheets else None)

        conf_schema = Dataframe.CONF_SCHEMA.copy()
        one_of = conf_schema.get("properties", {}).get("source", {}).get("oneOf", [])
        if one_of:
            file_source_schema = one_of[0]
            file_source_schema["properties"]["sheet"]["choices"] = sheets
        self.fields["conf"].schema = conf_schema

        col_schema = Dataframe.COL_SCHEMA.copy()
        col_schema["keys"]["column"]["choices"] = columns
        cols_schema = Dataframe.COLS_SCHEMA.copy()
        cols_schema["items"] = col_schema
        self.fields["cols"].schema = cols_schema

    @staticmethod
    def _get_sheet_names(file_path):
        if file_path.endswith(".csv"):
            return ["Sheet1"]
        try:
            return pd.ExcelFile(file_path, engine="calamine").sheet_names
        except Exception:
            return []

    @staticmethod
    def _get_columns(file_path, sheet_name=None):
        try:
            if file_path.endswith(".csv"):
                df = pd.read_csv(file_path, dtype=str)
            else:
                df = pd.read_excel(file_path, engine="calamine", dtype=str, sheet_name=sheet_name or 0)
            return [str(col) for col in df.columns]
        except Exception:
            return []
