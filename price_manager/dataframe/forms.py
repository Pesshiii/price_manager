from __future__ import annotations

import json

from django import forms

from .models import Dataframe
from .registry import READERS, TRANSFORMS


class DataframeForm(forms.ModelForm):
    instructions_json = forms.CharField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Dataframe
        fields = ['name', 'description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.instructions:
            self.fields['instructions_json'].initial = json.dumps(
                self.instance.instructions, ensure_ascii=False
            )
        self.fields['name'].widget.attrs.update({'class': 'form-control'})
        self.fields['description'].widget.attrs.update({'class': 'form-control', 'rows': 2})

    def clean(self):
        data = super().clean()
        raw = data.get('instructions_json') or ''
        if raw:
            try:
                instructions = json.loads(raw)
            except json.JSONDecodeError as e:
                raise forms.ValidationError(f'Невалидный JSON инструкций: {e}')
        else:
            instructions = {'reader': {'func': '', 'args': {}}, 'transforms': []}

        reader = instructions.get('reader') or {}
        rname = reader.get('func')
        if not rname:
            raise forms.ValidationError('Не выбрана функция чтения файла.')
        if rname not in READERS:
            raise forms.ValidationError(f"Неизвестная функция чтения: {rname}")
        for i, step in enumerate(instructions.get('transforms') or []):
            tname = step.get('func')
            if tname not in TRANSFORMS:
                raise forms.ValidationError(
                    f"Шаг {i+1}: неизвестная трансформация '{tname}'"
                )
        self.instance.instructions = instructions
        return data


class PreviewUploadForm(forms.Form):
    file = forms.FileField(label='Файл для превью')


class ConvertForm(forms.Form):
    dataframe = forms.ModelChoiceField(
        queryset=Dataframe.objects.all(), label='Dataframe',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    file = forms.FileField(label='Файл',
                           widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
