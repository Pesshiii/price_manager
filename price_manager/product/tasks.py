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
from django.conf import settings
from django.utils import timezone

from dataframe import sessions as session_store
from dataframe.models import Dataframe
from dataframe.services import apply as apply_pipeline

from .importer import IMPORT_COMMIT_BATCH_SIZE, apply_mapping, commit_rows
from .models import CharacteristicMutationJob, CharacteristicType, ImportJob, Product
from .services.embeddings import (
    EmbeddingServiceError,
    build_embedding_text,
    embed_texts,
    text_hash,
)
from .services.char_mutation import (
    ONCONFLICT_KEEP_EXISTING,
    ONCONFLICT_OVERWRITE,
    ONCONFLICT_SKIP_ROW,
    _make_probe,
    coerce_with_strategy,
)

logger = logging.getLogger(__name__)


STAGE_OPENING_SESSION = 'Открываем сессию'
STAGE_APPLYING_PIPELINE = 'Применяем pipeline'
STAGE_VALIDATING_ROWS = 'Валидируем строки'
STAGE_WRITING_DB = 'Записываем в БД'

# Stages for CharacteristicMutationJob — coarse boundaries, no per-row counter.
STAGE_SCANNING_PRODUCTS = 'Сканируем товары'
STAGE_APPLYING_MUTATION = 'Применяем изменения'
STAGE_UPDATING_TYPE = 'Обновляем тип'


def _set_stage(job, text: str) -> None:
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


def _mark_running(job, initial_stage: str = STAGE_OPENING_SESSION) -> None:
    job.status = job.STATUS_RUNNING
    job.started_at = timezone.now()
    job.stage = initial_stage
    job.save(update_fields=['status', 'started_at', 'stage'])


def _mark_success(job, result: dict) -> None:
    job.status = job.STATUS_SUCCESS
    job.result = result
    job.stage = ''
    job.finished_at = timezone.now()
    job.save(update_fields=['status', 'result', 'stage', 'finished_at'])


def _mark_error(job, exc: Exception) -> None:
    job.status = job.STATUS_ERROR
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

        # Kick off embedding refresh for affected products in the background.
        # Chunked so a 50k-row import doesn't put one huge task on the queue.
        affected_ids = summary.pop('affected_ids', []) or []
        chunk = max(1, settings.EMBED_BACKFILL_BATCH_SIZE)
        for i in range(0, len(affected_ids), chunk):
            embed_products_task.delay(affected_ids[i:i + chunk])

        _mark_success(job, summary)
    except FileNotFoundError as exc:
        _mark_error(job, exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception('run_import_commit failed for job %s', job_id)
        _mark_error(job, exc)


# --- CharacteristicType mutation tasks -------------------------------------

def _iter_products_with_key(name: str):
    """Yield Product rows that carry ``name`` in their JSONB ``characteristics``.

    Uses ``only()`` + ``iterator(chunk_size=…)`` to keep worker memory bounded
    on 50k+ catalogs — same pattern as ``importer.commit_rows``.
    """
    return (
        Product.objects
        .filter(characteristics__has_key=name)
        .only('id', 'characteristics')
        .iterator(chunk_size=max(IMPORT_COMMIT_BATCH_SIZE, 500))
    )


def _flush_batch(batch: list[Product]) -> None:
    if not batch:
        return
    Product.objects.bulk_update(batch, ['characteristics'])
    batch.clear()


@shared_task
def run_char_retype(job_id: str) -> None:
    """Migrate every product's JSONB value for ``ct.name`` to a new ``value_type``.

    Strategy precedence per product:
      1. ``payload['value_map'][raw_repr]`` overrides the raw value;
      2. otherwise ``payload['fallback']`` (drop/null/default) decides;
      3. if the original value coerces cleanly, it's just rewritten typed.
    """
    try:
        job = CharacteristicMutationJob.objects.select_related('char_type').get(
            pk=job_id, kind=CharacteristicMutationJob.KIND_RETYPE
        )
    except CharacteristicMutationJob.DoesNotExist:
        logger.warning('run_char_retype: job %s not found', job_id)
        return

    _mark_running(job, initial_stage=STAGE_SCANNING_PRODUCTS)
    try:
        ct = job.char_type
        payload = job.payload or {}
        new_value_type = payload['new_value_type']
        probe = _make_probe(ct, new_value_type)

        _set_stage(job, STAGE_APPLYING_MUTATION)
        counters = {'updated': 0, 'mapped': 0, 'defaulted': 0, 'nulled': 0, 'dropped': 0}
        batch: list[Product] = []
        batch_size = max(IMPORT_COMMIT_BATCH_SIZE, 100)

        for product in _iter_products_with_key(ct.name):
            chars = dict(product.characteristics or {})
            raw = chars.get(ct.name)
            action, new_value = coerce_with_strategy(probe, raw, payload)
            if action == 'dropped':
                chars.pop(ct.name, None)
                counters['dropped'] += 1
            elif action == 'nulled':
                chars[ct.name] = None
                counters['nulled'] += 1
            elif action == 'defaulted':
                if new_value is None:
                    chars.pop(ct.name, None)
                else:
                    chars[ct.name] = new_value
                counters['defaulted'] += 1
            elif action == 'mapped':
                chars[ct.name] = new_value
                counters['mapped'] += 1
            else:  # 'keep' — already coerced cleanly
                if new_value is None:
                    chars.pop(ct.name, None)
                else:
                    chars[ct.name] = new_value
            counters['updated'] += 1
            product.characteristics = chars
            batch.append(product)
            if len(batch) >= batch_size:
                _flush_batch(batch)

        _flush_batch(batch)

        _set_stage(job, STAGE_UPDATING_TYPE)
        ct.value_type = new_value_type
        ct.save(update_fields=['value_type'])

        _mark_success(job, counters)
    except Exception as exc:  # noqa: BLE001
        logger.exception('run_char_retype failed for job %s', job_id)
        _mark_error(job, exc)


@shared_task
def run_char_rename(job_id: str) -> None:
    """Rename a CharacteristicType slug, migrating the JSONB key in every product.

    Collision strategy (``payload['on_conflict']``):
      * ``overwrite`` — replace the value under ``new_name`` with the old one.
      * ``keep_existing`` — drop the old key, keep whatever's already at ``new_name``.
      * ``skip_row`` — leave the product untouched (both keys remain).
    """
    try:
        job = CharacteristicMutationJob.objects.select_related('char_type').get(
            pk=job_id, kind=CharacteristicMutationJob.KIND_RENAME
        )
    except CharacteristicMutationJob.DoesNotExist:
        logger.warning('run_char_rename: job %s not found', job_id)
        return

    _mark_running(job, initial_stage=STAGE_SCANNING_PRODUCTS)
    try:
        ct = job.char_type
        payload = job.payload or {}
        old_name = ct.name
        new_name = payload['new_name']
        on_conflict = payload.get('on_conflict', ONCONFLICT_OVERWRITE)
        if new_name == old_name:
            raise ValueError('new_name must differ from current name')

        _set_stage(job, STAGE_APPLYING_MUTATION)
        counters = {'renamed': 0, 'collisions': 0, 'skipped': 0}
        batch: list[Product] = []
        batch_size = max(IMPORT_COMMIT_BATCH_SIZE, 100)

        for product in _iter_products_with_key(old_name):
            chars = dict(product.characteristics or {})
            if new_name in chars:
                counters['collisions'] += 1
                if on_conflict == ONCONFLICT_SKIP_ROW:
                    counters['skipped'] += 1
                    continue
                if on_conflict == ONCONFLICT_KEEP_EXISTING:
                    chars.pop(old_name, None)
                else:  # overwrite
                    chars[new_name] = chars.pop(old_name)
            else:
                chars[new_name] = chars.pop(old_name)
            counters['renamed'] += 1
            product.characteristics = chars
            batch.append(product)
            if len(batch) >= batch_size:
                _flush_batch(batch)

        _flush_batch(batch)

        _set_stage(job, STAGE_UPDATING_TYPE)
        ct.name = new_name
        ct.save(update_fields=['name'])

        _mark_success(job, counters)
    except Exception as exc:  # noqa: BLE001
        logger.exception('run_char_rename failed for job %s', job_id)
        _mark_error(job, exc)


# --- Embedding tasks -------------------------------------------------------

def _embed_and_save(products: list[Product]) -> int:
    """Compute embeddings for ``products`` and write only the rows whose text
    actually changed (idempotent re-runs). Returns the number of rows written.
    """
    if not products:
        return 0

    char_keys: set[str] = set()
    for p in products:
        if isinstance(p.characteristics, dict):
            char_keys.update(p.characteristics.keys())
    types_by_name = (
        {ct.name: ct for ct in CharacteristicType.objects.filter(name__in=char_keys).only(
            'name', 'label', 'unit'
        )}
        if char_keys else {}
    )

    texts = [build_embedding_text(p, types_by_name) for p in products]
    hashes = [text_hash(t) for t in texts]

    todo_idx = [
        i for i, p in enumerate(products)
        if p.embedding_text_hash != hashes[i] or p.embedding is None
    ]
    if not todo_idx:
        return 0

    vectors = embed_texts([texts[i] for i in todo_idx])
    to_update: list[Product] = []
    for vec_pos, src_idx in enumerate(todo_idx):
        product = products[src_idx]
        product.embedding = vectors[vec_pos]
        product.embedding_text_hash = hashes[src_idx]
        to_update.append(product)

    Product.objects.bulk_update(to_update, ['embedding', 'embedding_text_hash'])
    return len(to_update)


@shared_task(
    name='product.embed_products',
    autoretry_for=(EmbeddingServiceError,),
    retry_backoff=True,
    retry_kwargs={'max_retries': 5},
)
def embed_products_task(product_ids: list[int]) -> dict:
    """Compute and persist embeddings for the given product ids.

    Used by post_save signal + after-import hook + manual backfill batches.
    Idempotent: rows whose ``embedding_text_hash`` matches the current text
    are skipped (no Ollama call for unchanged rows in a re-run).
    """
    if not product_ids:
        return {'updated': 0}
    products = list(
        Product.objects.filter(pk__in=product_ids).select_related('brand', 'category')
    )
    updated = _embed_and_save(products)
    return {'updated': updated, 'requested': len(product_ids)}


@shared_task(name='product.embed_missing_products')
def embed_missing_products_task() -> dict:
    """Periodic backfill: fill embeddings for products that don't have one yet.

    Bounded by ``EMBED_BACKFILL_BATCH_SIZE`` × ``EMBED_BACKFILL_MAX_BATCHES`` so
    one beat tick can't monopolize the worker. Remaining products are picked
    up by the next tick.
    """
    batch_size = settings.EMBED_BACKFILL_BATCH_SIZE
    max_batches = settings.EMBED_BACKFILL_MAX_BATCHES
    total_updated = 0
    total_seen = 0
    for _ in range(max_batches):
        ids = list(
            Product.objects.filter(embedding__isnull=True)
            .order_by('pk')
            .values_list('pk', flat=True)[:batch_size]
        )
        if not ids:
            break
        total_seen += len(ids)
        try:
            result = embed_products_task.apply(args=[ids]).get()
        except EmbeddingServiceError as exc:
            logger.warning('embed_missing_products: embedder down (%s), will retry next tick', exc)
            break
        total_updated += result.get('updated', 0)
    return {'seen': total_seen, 'updated': total_updated}
