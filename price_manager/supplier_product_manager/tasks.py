from celery import shared_task
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone
from django.conf import settings

from core.models import PersistentNotification
from core.task_runner import execute_locked_task
from main_product_manager.utils import compute_supplier_sku, link_to_local_products
from main_product_manager.models import MainProduct

from . import guard
from .functions import (
    SupplierFileStorageMissingError,
    SupplierImportError,
    _get_setting_signature,
    apply_counts,
    duplicate_warning,
    get_sps_result,
    load_setting,
    price_changes,
)
from .filters import SupplierProductFilter
from .models import (
    CopySupplierProductsToMainRun,
    ImportRun,
    Setting,
    Supplier,
    SupplierFile,
    SupplierProduct,
)


# Imports of one setting never overlap (process_supplier_file_import). An
# import that outlives this loses its lock, so it is generous.
IMPORT_LOCK_TTL_SECONDS = 60 * 30


def _append_supplier_file_log(supplier_file: SupplierFile | None, message: str) -> None:
    if supplier_file is None:
        return
    timestamp = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
    current_logs = supplier_file.logs or ""
    next_line = f"[{timestamp}] {message}"
    supplier_file.logs = f"{current_logs}\n{next_line}".strip()
    # A queryset update, not save(update_fields=...): the file may have been
    # deleted while the import ran, and a log line must not fail the import.
    SupplierFile.objects.filter(pk=supplier_file.pk).update(logs=supplier_file.logs)


def _set_file_status(supplier_file: SupplierFile | None, status: int) -> None:
    if supplier_file is None:
        return
    supplier_file.status = status
    SupplierFile.objects.filter(pk=supplier_file.pk).update(status=status)


_RUN_OUTCOME_FIELDS = ("status", "message", "finished_at", "guard_reasons", "mapped_keys",
                       "price_changes", *ImportRun.COUNTER_FIELDS)


def _finish_run(run: ImportRun, status: str, stats: dict, message: str = "") -> None:
    run.record_stats(stats)
    run.status = status
    run.message = message
    run.finished_at = timezone.now()
    # Only the outcome fields. A full save() wrote back supplier_file too, and
    # once that file was deleted mid-run the stale FK failed the save — after
    # the data was already committed, leaving the run "running" for good and
    # the user without a notification.
    ImportRun.objects.filter(pk=run.pk).update(
        **{name: getattr(run, name) for name in _RUN_OUTCOME_FIELDS})


def _hold_for_confirmation(run, setting, supplier_file, user_id, stats, verdict) -> dict:
    """Не применять: сохранить счётчики и причины и попросить подтверждения."""
    run.guard_reasons = verdict.reasons
    _finish_run(run, ImportRun.STATUS_NEEDS_CONFIRMATION, stats)
    reasons = "; ".join(run.reason_lines())
    message = f"Импорт «{setting.name}» ждёт подтверждения: {reasons}."
    warning = duplicate_warning(stats)
    if warning:
        message = f"{message} {warning}"
    _append_supplier_file_log(supplier_file, message)
    _set_file_status(supplier_file, SupplierFile.STATUS_NEEDS_CONFIRMATION)
    PersistentNotification.objects.create(
        user_id=user_id,
        level="warning",
        message=message,
        link=import_confirmation_link(run),
        link_text="Проверить",
    )
    return {"status": "needs_confirmation", "run_id": run.pk, "message": message}


def import_confirmation_link(run: ImportRun) -> str:
    """Страница поставщика, которая сразу открывает окно подтверждения этого импорта."""
    return f"{reverse('supplier-detail', kwargs={'pk': run.supplier_id})}?import_run={run.pk}#settings"


@shared_task
def process_supplier_file_import(setting_id: int, user_id: int, confirmed_run_id: int | None = None) -> dict:
    """
    Асинхронная обработка файла поставщика по настройке.

    Без confirmed_run_id файл сначала проверяется (guard.evaluate) и при
    подозрительно низком покрытии не применяется, а ждёт подтверждения.
    С confirmed_run_id применяется ровно тот файл и то сопоставление, что
    были показаны пользователю в окне подтверждения, — без повторной проверки.

    Импорты одной настройки не идут параллельно: пока один выполняется,
    следующий не запускается, а пользователь получает уведомление.
    """
    try:
        setting = Setting.objects.get(pk=setting_id)
    except Setting.DoesNotExist:
        return {"status": "error", "message": f"Настройка #{setting_id} не найдена"}

    result = {}

    def runner():
        result.update(_import_setting(setting, user_id, confirmed_run_id))
        return result.get("processed_rows", 0)

    # Not atomic: load_setting commits the data in its own transaction, and
    # the run, file status and notification must be written whatever happens.
    lock = execute_locked_task(
        task_name=f"supplier_import:setting:{setting.pk}",
        lock_ttl=IMPORT_LOCK_TTL_SECONDS,
        runner=runner,
        atomic=False,
    )
    if lock["status"] == "skipped":
        return _refuse_busy(setting, user_id, confirmed_run_id)
    return result


def _refuse_busy(setting: Setting, user_id: int, confirmed_run_id: int | None) -> dict:
    """Импорт этой настройки уже выполняется: второй не запускается.

    Двойной клик или новый файл, загруженный во время импорта, раньше давали
    два параллельных применения одной настройки.
    """
    reason = "эта настройка уже импортируется. Дождитесь окончания и запустите снова"
    if confirmed_run_id:
        # The user confirmed it, the apply just could not start: back to
        # pending, so "Применить" in the dialog works again.
        ImportRun.objects.filter(pk=confirmed_run_id, status=ImportRun.STATUS_RUNNING).update(
            status=ImportRun.STATUS_NEEDS_CONFIRMATION, confirmed_by=None, confirmed_at=None)
    else:
        supplier_file = setting.supplierfiles.order_by("-pk").first()
        in_progress = supplier_file is not None and ImportRun.objects.filter(
            setting=setting, supplier_file=supplier_file, status=ImportRun.STATUS_RUNNING,
        ).exists()
        # The view marked the latest file queued. If the running import is
        # not reading that very file, it will never be processed.
        if supplier_file is not None and not in_progress:
            _append_supplier_file_log(supplier_file, f"Импорт не запущен: {reason}")
            _set_file_status(supplier_file, SupplierFile.STATUS_ERROR)
    message = f"Импорт «{setting.name}» не запущен: {reason}."
    PersistentNotification.objects.create(user_id=user_id, level="warning", message=message)
    return {"status": "busy", "message": message}


def _import_setting(setting: Setting, user_id: int, confirmed_run_id: int | None) -> dict:
    started_at = timezone.now()
    setting_id = setting.pk

    supplier_file = setting.supplierfiles.order_by("-pk").first()
    if supplier_file:
        supplier_file.status, supplier_file.logs = SupplierFile.STATUS_RUNNING, ""
        SupplierFile.objects.filter(pk=supplier_file.pk).update(status=supplier_file.status, logs="")

    _append_supplier_file_log(
        supplier_file,
        f"Запущена обработка настройки «{setting.name}» (ID={setting_id})",
    )
    if confirmed_run_id:
        run = ImportRun.objects.get(pk=confirmed_run_id, setting=setting)
        if (run.supplier_file_id != (supplier_file.pk if supplier_file else None)
                or run.signature != _get_setting_signature(setting)):
            reason = "Файл или настройка изменились после проверки — запустите импорт заново"
            _finish_run(run, ImportRun.STATUS_SUPERSEDED, {}, reason)
            _append_supplier_file_log(supplier_file, reason)
            PersistentNotification.objects.create(
                user_id=user_id, level="warning",
                message=f"Импорт «{setting.name}» не применён: {reason}.",
            )
            return {"status": "superseded", "message": reason}
    else:
        # A newer import of the same setting makes an unconfirmed one moot.
        ImportRun.objects.filter(
            setting=setting, status=ImportRun.STATUS_NEEDS_CONFIRMATION,
        ).update(status=ImportRun.STATUS_SUPERSEDED, message="Запущен новый импорт",
                 finished_at=timezone.now())
        run = ImportRun.objects.create(
            setting=setting,
            supplier_id=setting.supplier_id,
            supplier_file=supplier_file,
            file_name=supplier_file.file.name if supplier_file and supplier_file.file else "",
            user_id=user_id,
            signature=_get_setting_signature(setting),
        )

    try:
        _append_supplier_file_log(supplier_file, "Чтение и обработка файла")
        payload, parse_stats = get_sps_result(setting)
        changes = price_changes(setting, payload)
        stats = {**parse_stats, **apply_counts(setting, payload), "price_changes": changes}
        if not confirmed_run_id:
            verdict = guard.evaluate(setting, stats, exclude_pk=run.pk)
            if not verdict.ok:
                return _hold_for_confirmation(run, setting, supplier_file, user_id, stats, verdict)

        outcome = load_setting(setting_id, parsed=(payload, parse_stats))
        duration_seconds = round((timezone.now() - started_at).total_seconds(), 2)
        stats = {**outcome.stats, "price_changes": changes}
        processed_rows = len(outcome.sps)
        message = (
            f"Импорт «{setting.name}» завершен: обработано строк {processed_rows} "
            f"(с ценой {stats.get('covered_price', 0)}, с остатком {stats.get('covered_stock', 0)}), "
            f"новых {stats.get('created', 0)}, "
            + (f"переименовано {stats['renamed']}, " if stats.get('renamed') else "")
            + f"нет в файле {stats.get('missing', 0)}"
            + (f" (привязаны к ГП {stats['missing_linked']})" if stats.get('missing_linked') else "")
            + ", "
            f"длительность {duration_seconds} сек."
        )
        # Repeated rows and articles with several names do not stop an import,
        # but the user has to hear about them: the latter usually mean variants
        # under one article, sometimes a broken price list.
        warning = duplicate_warning(stats)
        if warning:
            message = f"{message} {warning}"

        _finish_run(run, ImportRun.STATUS_APPLIED, stats)
        _append_supplier_file_log(supplier_file, message)
        _set_file_status(supplier_file, SupplierFile.STATUS_SUCCESS)

        PersistentNotification.objects.create(
            user_id=user_id,
            level="warning" if warning else "success",
            message=message,
        )
        return {
            "status": "ok",
            "processed_rows": processed_rows,
            "errors": 0,
            "duration_seconds": duration_seconds,
            "message": message,
        }
    except (SupplierImportError, SupplierFileStorageMissingError) as exc:
        # Expected refusals: the file or the setting is wrong, not the code.
        # Reported to the user with the reason and not re-raised.
        duration_seconds = round((timezone.now() - started_at).total_seconds(), 2)
        storage_missing = isinstance(exc, SupplierFileStorageMissingError)
        reason = "Файл настройки отсутствует в media-хранилище." if storage_missing else str(exc)
        error_message = (
            f"Импорт «{setting.name}» не выполнен, данные не изменены. Причина: {reason} "
            f"(длительность {duration_seconds} сек.)"
        )
        _finish_run(run, ImportRun.STATUS_REFUSED, getattr(exc, "stats", {}), reason)
        _append_supplier_file_log(supplier_file, f"{error_message} ({exc})" if storage_missing else error_message)
        _set_file_status(supplier_file, SupplierFile.STATUS_ERROR)
        PersistentNotification.objects.create(
            user_id=user_id,
            level="danger",
            message=error_message,
        )
        return {
            "status": "error",
            "processed_rows": 0,
            "errors": 1,
            "duration_seconds": duration_seconds,
            "message": error_message,
        }
    except Exception as exc:
        duration_seconds = round((timezone.now() - started_at).total_seconds(), 2)
        error_message = (
            f"Импорт «{setting.name}» завершен с ошибкой: обработано строк 0, ошибок 1, "
            f"длительность {duration_seconds} сек. Причина: {exc}"
        )
        _finish_run(run, ImportRun.STATUS_FAILED, {}, str(exc))
        _append_supplier_file_log(supplier_file, error_message)
        _set_file_status(supplier_file, SupplierFile.STATUS_ERROR)
        PersistentNotification.objects.create(
            user_id=user_id,
            level="danger",
            message=error_message,
        )
        raise


@shared_task
def process_setting_upload(setting_id: int, user_id: int) -> dict:
    """Совместимость со старым названием задачи."""
    return process_supplier_file_import(setting_id, user_id)

@shared_task(name="supplier_product_manager.cleanup_supplier_files_task")
def cleanup_supplier_files_task() -> dict:
    """
    Удаляет старые SupplierFile, оставляя только последние N файлов на каждую настройку.

    Последний файл настройки не удаляется никогда (N не меньше 1): его читают
    экран сопоставления колонок и импорт. Файлы в очереди, в обработке или
    ждущие подтверждения импорта тоже не трогаются.
    """
    keep_last = max(getattr(settings, "SUPPLIER_FILES_KEEP_LAST", 1), 1)
    deleted_count = 0
    in_progress = (SupplierFile.STATUS_QUEUED, SupplierFile.STATUS_RUNNING,
                   SupplierFile.STATUS_NEEDS_CONFIRMATION)

    for setting in Setting.objects.only("id").iterator():
        file_ids = list(
            setting.supplierfiles.order_by("-pk").values_list("pk", flat=True)
        )
        ids_to_delete = file_ids[keep_last:]
        if not ids_to_delete:
            continue

        stale_files = SupplierFile.objects.filter(pk__in=ids_to_delete).exclude(status__in=in_progress)
        for supplier_file in stale_files.iterator():
            supplier_file.delete()
            deleted_count += 1

    orphan_files = SupplierFile.objects.filter(setting__isnull=True).only("pk", "file")
    for supplier_file in orphan_files.iterator():
        supplier_file.delete()
        deleted_count += 1

    return {
        "status": "ok",
        "keep_last": keep_last,
        "deleted_count": deleted_count,
    }

def _restore_querydict(filter_params: dict | None) -> QueryDict:
    query_dict = QueryDict("", mutable=True)
    if not filter_params:
        return query_dict
    for key, value in filter_params.items():
        if isinstance(value, list):
            query_dict.setlist(key, [str(v) for v in value if v is not None])
        elif value is not None:
            query_dict[key] = str(value)
    return query_dict


def _chunked(iterable, chunk_size: int):
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


@shared_task
def copy_supplier_products_to_main_task(
    supplier_id: int,
    filter_params: dict | None,
    user_id: int,
    run_id: int | None = None,
    batch_size: int = 1000,
) -> dict:
    started_at = timezone.now()
    run = None

    if run_id:
        run = CopySupplierProductsToMainRun.objects.filter(pk=run_id).first()
        if run:
            run.status = CopySupplierProductsToMainRun.STATUS_STARTED
            run.error = None
            run.save(update_fields=["status", "error"])

    try:
        query_data = _restore_querydict(filter_params)
        products_qs = (
            SupplierProductFilter(query_data, pk=supplier_id)
            .qs.select_related("main_product", "supplier")
            .filter(supplier_id=supplier_id)
            .order_by("pk")
        )

        created_count = products_qs.filter(main_product__isnull=True).count()
        processed_count = 0
        updated_links_count = 0
        touched_main_product_ids = set()
        supplier = Supplier.objects.get(id=supplier_id)

        for batch in _chunked(products_qs.iterator(chunk_size=batch_size), batch_size):
            processed_count += len(batch)
            if not batch:
                continue

            # Уже связанным строкам копировать больше нечего: производитель,
            # описание и категории у MainProduct удалены в Phase 2b. Остаётся
            # только проверить их связь с товаром (ниже).
            linked = [sp for sp in batch if sp.main_product_id]
            unlinked = [sp for sp in batch if not sp.main_product_id]
            touched_main_product_ids.update(sp.main_product_id for sp in linked)

            if unlinked:
                new_mps = [
                    MainProduct(
                        supplier_id=supplier_id,
                        article=sp.article,
                        sku=compute_supplier_sku(sp.article, supplier),
                        name=sp.name,
                    )
                    for sp in unlinked
                ]
                MainProduct.objects.bulk_create(new_mps, batch_size=batch_size)

                for sp, mp in zip(unlinked, new_mps):
                    sp.main_product_id = mp.id
                    touched_main_product_ids.add(mp.id)

                SupplierProduct.objects.bulk_update(unlinked, fields=["main_product"], batch_size=batch_size)
                updated_links_count += len(unlinked)

        # Связь с товаром (product.Product) — явно. До Phase 2b она ставилась
        # побочным эффектом пересборки search_vector; без этого шага каждая
        # новая строка ложилась бы с product IS NULL и не показывалась на
        # /products/ до ночного reindex_pim_ids — без единой ошибки.
        for ids_chunk in _chunked(list(touched_main_product_ids), batch_size):
            link_to_local_products(ids_chunk)

        duration_seconds = round((timezone.now() - started_at).total_seconds(), 2)
        message = (
            f"Копирование товаров поставщика завершено: обработано {processed_count}, "
            f"создано новых {created_count}, обновлено связей {updated_links_count}, "
            f"длительность {duration_seconds} сек."
        )

        if run:
            run.status = CopySupplierProductsToMainRun.STATUS_SUCCESS
            run.processed_count = processed_count
            run.created_count = created_count
            run.updated_links_count = updated_links_count
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "processed_count",
                    "created_count",
                    "updated_links_count",
                    "finished_at",
                ]
            )

        PersistentNotification.objects.create(
            user_id=user_id,
            level="success",
            message=message,
        )
        return {
            "status": "ok",
            "processed_count": processed_count,
            "created_count": created_count,
            "updated_links_count": updated_links_count,
            "duration_seconds": duration_seconds,
            "message": message,
        }
    except Exception as exc:
        if run:
            run.status = CopySupplierProductsToMainRun.STATUS_ERROR
            run.error = str(exc)
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error", "finished_at"])
        PersistentNotification.objects.create(
            user_id=user_id,
            level="danger",
            message=f"Ошибка копирования товаров поставщика: {exc}",
        )
        raise
