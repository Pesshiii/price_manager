"""Celery tasks for the supplier_feed application.

Public task:
    run_feed_matching_task(feed_id)  — orchestrates file reading + matching.

Status lifecycle driven by this task:
    processing  ──success, queued=0──►  matched
    processing  ──success, queued>0──►  partial
    processing  ──exception         ──►  error

Concurrency: a per-feed Redis lock prevents parallel runs for the same feed.
"""
from __future__ import annotations

import io
import logging

import pandas as pd
from celery import shared_task
from django.core.cache import cache

from dataframe import sessions as session_store

from . import matcher
from .models import (
    SupplierFeed,
    STATUS_MATCHED,
    STATUS_PARTIAL,
    STATUS_ERROR,
)

logger = logging.getLogger(__name__)

_LOCK_TTL = 3600  # seconds


def _build_lock_key(feed_id: int) -> str:
    return f'supplier-feed-matching:{feed_id}'


def _read_rows_from_sessions(feed: SupplierFeed) -> list[dict]:
    """Open each session file attached to the feed and parse it to a list of row dicts."""
    all_rows: list[dict] = []
    for session_id in feed.session_ids:
        fobj = session_store.open_session_file(session_id)
        try:
            raw = fobj.read()
            filename = session_store.session_filename(session_id)
            if filename.lower().endswith(('.xlsx', '.xls')):
                df = pd.read_excel(io.BytesIO(raw))
            else:
                df = pd.read_csv(io.BytesIO(raw))
            all_rows.extend(df.to_dict(orient='records'))
        finally:
            try:
                fobj.close()
            except Exception:
                pass
    return all_rows


def _cleanup_sessions(feed: SupplierFeed) -> None:
    for session_id in list(feed.session_ids):
        try:
            session_store.delete_session(session_id)
        except Exception:
            logger.warning(
                'run_feed_matching_task: delete_session failed for %s', session_id,
                exc_info=True,
            )


@shared_task
def run_feed_matching_task(feed_id: int) -> None:
    """Match all rows in a SupplierFeed session against the Product catalogue.

    Sets ``feed.status`` to 'matched', 'partial', or 'error' when done.
    Uses a Redis lock to prevent concurrent execution for the same feed.
    """
    lock_key = _build_lock_key(feed_id)
    if not cache.add(lock_key, '1', timeout=_LOCK_TTL):
        logger.info('run_feed_matching_task: lock exists for feed %s, skipping', feed_id)
        return

    try:
        try:
            feed = SupplierFeed.objects.select_related('feed_mapping', 'supplier').get(
                pk=feed_id
            )
        except SupplierFeed.DoesNotExist:
            logger.warning('run_feed_matching_task: feed %s not found', feed_id)
            return

        try:
            rows = _read_rows_from_sessions(feed)
            stats = matcher.run_matching(feed, rows)

            _cleanup_sessions(feed)

            feed.status = STATUS_MATCHED if stats['queued'] == 0 else STATUS_PARTIAL
            feed.error = ''
            feed.save(update_fields=['status', 'error'])

        except Exception as exc:
            logger.exception(
                'run_feed_matching_task: error processing feed %s', feed_id
            )
            feed.status = STATUS_ERROR
            feed.error = f'{type(exc).__name__}: {exc}'
            feed.save(update_fields=['status', 'error'])

    finally:
        cache.delete(lock_key)
