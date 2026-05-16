from __future__ import annotations

from rest_framework import serializers

from ..models import Dataframe
from ..registry import READERS, TRANSFORMS, ArgSpec, ReaderSpec, TransformSpec


def _arg_to_dict(arg: ArgSpec) -> dict:
    return {
        'name': arg.name,
        'type': arg.type,
        'label': arg.label,
        'required': arg.required,
        'default': arg.default,
        'choices': list(arg.choices) if arg.choices else None,
        'help_text': arg.help_text,
    }


def serialize_reader(spec: ReaderSpec) -> dict:
    return {
        'name': spec.name,
        'label': spec.label,
        'extensions': list(spec.extensions),
        'args': [_arg_to_dict(a) for a in spec.args],
    }


def serialize_transform(spec: TransformSpec) -> dict:
    return {
        'name': spec.name,
        'label': spec.label,
        'args': [_arg_to_dict(a) for a in spec.args],
    }


class StepSerializer(serializers.Serializer):
    func = serializers.CharField()
    args = serializers.DictField(required=False, default=dict)


class ReaderConfigSerializer(serializers.Serializer):
    func = serializers.CharField()
    args = serializers.DictField(required=False, default=dict)

    def validate_func(self, value: str) -> str:
        if value not in READERS:
            raise serializers.ValidationError(f"Неизвестный reader: '{value}'")
        return value


class SourceSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=['upload', 'url'])
    url = serializers.URLField(required=False, allow_blank=True)


class InstructionsSerializer(serializers.Serializer):
    """Validates a pipeline definition against the registry."""
    reader = ReaderConfigSerializer()
    transforms = serializers.ListField(child=StepSerializer(), required=False, default=list)
    source = SourceSerializer(required=False)

    def validate_transforms(self, value):
        for i, step in enumerate(value):
            func = step.get('func')
            if func not in TRANSFORMS:
                raise serializers.ValidationError(
                    f"Шаг {i + 1}: неизвестная трансформация '{func}'"
                )
        return value


class DataframeSerializer(serializers.ModelSerializer):
    instructions = InstructionsSerializer()

    class Meta:
        model = Dataframe
        fields = ('id', 'name', 'description', 'instructions', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class PreviewRequestSerializer(serializers.Serializer):
    instructions = InstructionsSerializer()
    up_to = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    session_id = serializers.CharField(required=False, allow_blank=True)
    row_limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=1000)

    def validate(self, attrs):
        if not attrs.get('session_id'):
            raise serializers.ValidationError({'session_id': 'session_id обязателен.'})
        return attrs


class UploadSessionResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    filename = serializers.CharField()
    size = serializers.IntegerField()
