"""
Temporary upload sessions for the dataframe editor.

Хранит загруженный пользователем файл во временном префиксе
``dataframe_sessions/<session_id>/<filename>`` через ``default_storage``
(media/ локально, S3 в проде). TTL обеспечивается отдельной cleanup-задачей —
здесь мы только пишем и читаем.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from . import cache as df_cache

PREFIX = 'dataframe_sessions'
DEFAULT_TTL = timedelta(hours=24)


def _session_dir(session_id: str) -> str:
    if not session_id or '/' in session_id or '\\' in session_id or '..' in session_id:
        raise ValueError('Invalid session_id')
    return f'{PREFIX}/{session_id}'


def create_session(file_obj, filename: str) -> str:
    """Save uploaded file under a fresh session_id. Returns session_id."""
    session_id = uuid.uuid4().hex
    safe_name = PurePosixPath(filename).name or 'upload.bin'
    path = f'{_session_dir(session_id)}/{safe_name}'
    if hasattr(file_obj, 'seek'):
        try:
            file_obj.seek(0)
        except Exception:
            pass
    if hasattr(file_obj, 'read'):
        default_storage.save(path, ContentFile(file_obj.read(), name=safe_name))
    else:
        default_storage.save(path, ContentFile(bytes(file_obj), name=safe_name))
    return session_id


def open_session_file(session_id: str):
    """Open the (single) file stored for a session. Raises FileNotFoundError if missing."""
    base = _session_dir(session_id)
    try:
        _, files = default_storage.listdir(base)
    except FileNotFoundError:
        raise FileNotFoundError(session_id)
    if not files:
        raise FileNotFoundError(session_id)
    path = f'{base}/{files[0]}'
    return default_storage.open(path, 'rb')


def session_filename(session_id: str) -> str:
    base = _session_dir(session_id)
    _, files = default_storage.listdir(base)
    if not files:
        raise FileNotFoundError(session_id)
    return files[0]


def session_metadata(session_id: str) -> dict:
    """Return filename, size, uploaded_at for the session, or raise FileNotFoundError."""
    base = _session_dir(session_id)
    try:
        _, files = default_storage.listdir(base)
    except FileNotFoundError:
        raise FileNotFoundError(session_id)
    if not files:
        raise FileNotFoundError(session_id)
    name = files[0]
    path = f'{base}/{name}'
    try:
        size = default_storage.size(path)
    except Exception:
        size = 0
    try:
        uploaded_at = default_storage.get_modified_time(path).isoformat()
    except (NotImplementedError, Exception):
        uploaded_at = None
    return {
        'session_id': session_id,
        'filename': name,
        'size': size,
        'uploaded_at': uploaded_at,
    }


def delete_session(session_id: str) -> None:
    df_cache.invalidate_session(session_id)
    base = _session_dir(session_id)
    try:
        _, files = default_storage.listdir(base)
    except FileNotFoundError:
        return
    for name in files:
        default_storage.delete(f'{base}/{name}')


def cleanup_expired(ttl: timedelta = DEFAULT_TTL) -> int:
    """Remove session dirs older than ttl. Returns number of sessions removed."""
    cutoff = timezone.now() - ttl
    try:
        dirs, _ = default_storage.listdir(PREFIX)
    except FileNotFoundError:
        return 0
    removed = 0
    for sid in dirs:
        try:
            mtime = default_storage.get_modified_time(f'{PREFIX}/{sid}')
        except (NotImplementedError, FileNotFoundError):
            continue
        if mtime < cutoff:
            delete_session(sid)
            removed += 1
    return removed
