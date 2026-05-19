"""Celery tasks for asynchronous product import.

Each task is bound to one ImportJob row: it loads the job, runs the dataframe
pipeline + mapping, and writes back either a result payload (preview/commit) or
an error string. Clients poll /api/products/import/jobs/<id>/ for status.

The ``stage`` field on ImportJob is updated at coarse boundaries so the UI can
show what the worker is doing right now (no per-row progress — see plan).
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from dataframe import sessions as session_store
from dataframe.models import Dataframe
from dataframe.services import apply as apply_pipeline

from .importer import apply_mapping, commit_rows
from .models import ImportJob

logger = logging.getLogger(__name__)


STAGE_OPENING_SESSION = 'Открываем сессию'
STAGE_APPLYING_PIPELINE = 'Применяем pipeline'
STAGE_VALIDATING_ROWS = 'Валидируем строки'
STAGE_WRITING_DB = 'Записываем в БД'


def _set_stage(job: ImportJob, text: str) -> None:
    job.stage = text
    job.save(update_fields=['stage'])


def _run_pipeline_for_job(job: ImportJob):
    file_obj = session_store.open_session_file(job.session_id)
    try:
        df_obj = Dataframe(name='_import', instructions=dict(job.instructions or {}))
        return apply_pipeline(df_obj, file_obj, session_id=job.session_id)
    finally:
        try:
            file_obj.close()
        except Exception:
            pass


def _mark_running(job: ImportJob) -> None:
    job.status = ImportJob.STATUS_RUNNING
    job.started_at = timezone.now()
    job.stage = STAGE_OPENING_SESSION
    job.save(update_fields=['status', 'started_at', 'stage'])


def _mark_success(job: ImportJob, result: dict) -> None:
    job.status = ImportJob.STATUS_SUCCESS
    job.result = result
    job.stage = ''
    job.finished_at = timezone.now()
    job.save(update_fields=['status', 'result', 'stage', 'finished_at'])


def _mark_error(job: ImportJob, exc: Exception) -> None:
    job.status = ImportJob.STATUS_ERROR
    job.error = f'{type(exc).__name__}: {exc}'
    job.stage = ''
    job.finished_at = timezone.now()
    job.save(update_fields=['status', 'error', 'stage', 'finished_at'])


@shared_task
def run_import_preview(job_id: str) -> None:
    try:
        job = ImportJob.objects.get(pk=job_id, kind=ImportJob.KIND_PREVIEW)
    except ImportJob.DoesNotExist:
        logger.warning('run_import_preview: job %s not found', job_id)
        return

    _mark_running(job)
    try:
        _set_stage(job, STAGE_APPLYING_PIPELINE)
        df = _run_pipeline_for_job(job)
        _set_stage(job, STAGE_VALIDATING_ROWS)
        results = apply_mapping(df, job.mapping or {})
        limit = job.row_limit or 200
        preview_rows = [r.to_json() for r in results[:limit]]
        valid = sum(1 for r in results if r.is_valid)
        _mark_success(job, {
            'rows': preview_rows,
            'total': len(results),
            'returned': len(preview_rows),
            'valid': valid,
            'invalid': len(results) - valid,
        })
    except FileNotFoundError as exc:
        _mark_error(job, exc)
    except Exception as exc:  # noqa: BLE001 — surface to client via job.error
        logger.exception('run_import_preview failed for job %s', job_id)
        _mark_error(job, exc)


@shared_task
def run_import_commit(job_id: str) -> None:
    try:
        job = ImportJob.objects.get(pk=job_id, kind=ImportJob.KIND_COMMIT)
    except ImportJob.DoesNotExist:
        logger.warning('run_import_commit: job %s not found', job_id)
        return

    _mark_running(job)
    try:
        _set_stage(job, STAGE_APPLYING_PIPELINE)
        df = _run_pipeline_for_job(job)
        _set_stage(job, STAGE_VALIDATING_ROWS)
        results = apply_mapping(df, job.mapping or {})
        _set_stage(job, STAGE_WRITING_DB)
        summary = commit_rows(results)
        # Free the cached DataFrame and the upload file — both are large and
        # no longer needed once the commit lands. Failure here is non-fatal.
        try:
            session_store.delete_session(job.session_id)
        except Exception:
            logger.warning('delete_session after commit failed for job %s', job_id, exc_info=True)
        _mark_success(job, summary)
    except FileNotFoundError as exc:
        _mark_error(job, exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception('run_import_commit failed for job %s', job_id)
        _mark_error(job, exc)
