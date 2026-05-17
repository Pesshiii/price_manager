from __future__ import annotations

import math

import pandas as pd
from rest_framework import status, viewsets
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import sessions as session_store
from ..models import Dataframe
from ..registry import READERS, TRANSFORMS
from ..services import apply_partial
from .serializers import (
    DataframeSerializer,
    PreviewRequestSerializer,
    UploadSessionResponseSerializer,
    serialize_reader,
    serialize_transform,
)


class RegistryView(APIView):
    """GET /api/dataframe/registry/ — описание readers и transforms для UI."""

    def get(self, request):
        return Response({
            'readers': [serialize_reader(r) for r in READERS.values()],
            'transforms': [serialize_transform(t) for t in TRANSFORMS.values()],
        })


class DataframeViewSet(viewsets.ModelViewSet):
    """CRUD по сохранённым пайплайнам."""
    queryset = Dataframe.objects.all()
    serializer_class = DataframeSerializer


class UploadSessionView(APIView):
    """POST /api/dataframe/sessions/ — загрузить файл и получить session_id для preview."""
    parser_classes = [MultiPartParser]

    def post(self, request):
        file_obj = request.FILES.get('file')
        if file_obj is None:
            return Response({'detail': 'file обязателен.'}, status=status.HTTP_400_BAD_REQUEST)
        session_id = session_store.create_session(file_obj, file_obj.name)
        payload = UploadSessionResponseSerializer({
            'session_id': session_id,
            'filename': file_obj.name,
            'size': file_obj.size,
        }).data
        return Response(payload, status=status.HTTP_201_CREATED)

    def get(self, request, session_id: str):
        try:
            return Response(session_store.session_metadata(session_id))
        except (FileNotFoundError, ValueError):
            return Response(
                {'detail': f'session {session_id} не найдена.'},
                status=status.HTTP_404_NOT_FOUND,
            )

    def delete(self, request, session_id: str | None = None):
        sid = session_id or request.query_params.get('session_id')
        if not sid:
            return Response({'detail': 'session_id обязателен.'}, status=status.HTTP_400_BAD_REQUEST)
        session_store.delete_session(sid)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _dataframe_to_payload(df: pd.DataFrame, row_limit: int, offset: int = 0) -> dict:
    """Сериализует окно DataFrame в JSON-friendly формат с пагинацией."""
    total = int(df.shape[0])
    window = df.iloc[offset:offset + row_limit]
    cleaned = window.where(pd.notna(window), None)
    rows = []
    for record in cleaned.to_dict(orient='records'):
        row = []
        for col in window.columns:
            value = record.get(col)
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                value = None
            row.append(value)
        rows.append(row)
    returned = len(rows)
    return {
        'columns': [str(c) for c in window.columns],
        'rows': rows,
        'total_rows': total,
        'returned_rows': returned,
        'offset': offset,
        'has_more': (offset + returned) < total,
    }


class PreviewView(APIView):
    """POST /api/dataframe/preview/ — запустить пайплайн (опц. до шага up_to) и вернуть JSON."""
    parser_classes = [JSONParser]

    def post(self, request):
        serializer = PreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session_id = data['session_id']
        try:
            file_obj = session_store.open_session_file(session_id)
        except FileNotFoundError:
            return Response(
                {'detail': f'session {session_id} не найдена или истекла.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        instructions = data['instructions']
        df_obj = Dataframe(name='_preview', instructions=dict(instructions))
        up_to = data.get('up_to')

        try:
            df = apply_partial(df_obj, file_obj, up_to=up_to, session_id=session_id)
        except Exception as exc:  # noqa: BLE001 — surfacing pipeline errors to UI
            return Response(
                {
                    'error': {
                        'step_index': up_to,
                        'message': f'{type(exc).__name__}: {exc}',
                    },
                },
                status=status.HTTP_200_OK,
            )
        finally:
            try:
                file_obj.close()
            except Exception:
                pass

        payload = _dataframe_to_payload(df, row_limit=data['row_limit'], offset=data['offset'])
        return Response(payload)
