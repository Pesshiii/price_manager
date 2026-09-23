"""Create Bitrix24 tasks through an inbound webhook.

A webhook rather than the OAuth app that core/bitrix24.py logs people in with:
tasks are created by the server, not on behalf of whoever is logged in, so a
fixed webhook with the `task` scope needs no token storage or refresh.

The webhook URL embeds its secret code, so it is never logged. HTTP calls live
here so tests can patch `requests.post`.
"""
import logging
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 15


class Bitrix24Error(Exception):
    """Bitrix24 refused the request. Retrying the same request will not help."""


class Bitrix24Unavailable(Bitrix24Error):
    """Network failure or a 5xx: worth retrying."""


def is_configured() -> bool:
    return bool(
        settings.BITRIX24_FEEDBACK_WEBHOOK and settings.BITRIX24_FEEDBACK_RESPONSIBLE_ID
    )


def create_task(title: str, description: str, responsible_id: int) -> int:
    """tasks.task.add; returns the new task's id."""
    webhook = settings.BITRIX24_FEEDBACK_WEBHOOK
    host = urlparse(webhook).netloc
    try:
        response = requests.post(
            f"{webhook.rstrip('/')}/tasks.task.add.json",
            json={'fields': {
                'TITLE': title,
                'DESCRIPTION': description,
                'RESPONSIBLE_ID': responsible_id,
            }},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        # Class only: the message carries the URL, and the URL the secret.
        logger.warning('Bitrix24 request to %s failed: %s', host, type(exc).__name__)
        raise Bitrix24Unavailable(f'Bitrix24 недоступен ({type(exc).__name__})') from None

    if response.status_code >= 500:
        logger.warning('Bitrix24 %s answered HTTP %s', host, response.status_code)
        raise Bitrix24Unavailable(f'Bitrix24 ответил HTTP {response.status_code}')

    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {}

    if response.status_code >= 400 or 'error' in data:
        error = data.get('error_description') or data.get('error') or f'HTTP {response.status_code}'
        logger.warning('Bitrix24 %s rejected tasks.task.add: %s', host, error)
        raise Bitrix24Error(f'Bitrix24 отклонил создание задачи: {error}')

    task = (data.get('result') or {}).get('task') or {}
    try:
        return int(task['id'])
    except (KeyError, TypeError, ValueError):
        raise Bitrix24Error('Bitrix24 не вернул номер созданной задачи') from None
