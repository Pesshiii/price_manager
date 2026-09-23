from celery import shared_task
from django.http import QueryDict
from django.utils import timezone
from django.conf import settings

from core.models import PersistentNotification
from main_product_manager.utils import compute_supplier_sku, link_to_local_products
from main_product_manager.models import MainProduct

from .functions import load_setting, SupplierFileStorageMissingError, SupplierImportError
from .filters import SupplierProductFilter
from .models import (
    CopySupplierProductsToMainRun,
    ImportRun,
    Setting,
    Supplier,
    SupplierFile,
    SupplierProduct,
)


def _append_supplier_file_log(supplier_file: SupplierFile | None, message: str) -> None:
    if supplier_file is None:
        return
    timestamp = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
    current_logs = supplier_file.logs or ""
    next_line = f"[{timestamp}] {message}"
    supplier_file.logs = f"{current_logs}\n{next_line}".strip()
    supplier_file.save(update_fields=["logs"])


def _finish_run(run: ImportRun, status: str, stats: dict, message: str = "") -> None:
    run.record_stats(stats)
    run.status = status
    run.message = message
    run.finished_at = timezone.now()
    run.save()


@shared_task
def process_supplier_file_import(setting_id: int, user_id: int) -> dict:
    """
    Асинхронная обработка файла поставщика по настройке.
    """
    started_at = timezone.now()

    try:
        setting = Setting.objects.get(pk=setting_id)
    except Setting.DoesNotExist:
        return {"status": "error", "message": f"Настройка #{setting_id} не найдена"}

    supplier_file = setting.supplierfiles.order_by("-pk").first()
    if supplier_file:
        supplier_file.status = SupplierFile.STATUS_RUNNING
        supplier_file.logs = ""
        supplier_file.save(update_fields=["status", "logs"])

    _append_supplier_file_log(
        supplier_file,
        f"Запущена обработка настройки «{setting.name}» (ID={setting_id})",
    )
    run = ImportRun.objects.create(
        setting=setting,
        supplier_id=setting.supplier_id,
        supplier_file=supplier_file,
        file_name=supplier_file.file.name if supplier_file and supplier_file.file else "",
        user_id=user_id,
    )

    try:
        _append_supplier_file_log(supplier_file, "Чтение и обработка файла")
        outcome = load_setting(setting_id)
        duration_seconds = round((timezone.now() - started_at).total_seconds(), 2)
        stats = outcome.stats
        processed_rows = len(outcome.sps)
        message = (
            f"Импорт «{setting.name}» завершен: обработано строк {processed_rows} "
            f"(с ценой {stats.get('covered_price', 0)}, с остатком {stats.get('covered_stock', 0)}), "
            f"новых {stats.get('created', 0)}, нет в файле {stats.get('missing', 0)}, "
            f"длительность {duration_seconds} сек."
        )

        _finish_run(run, ImportRun.STATUS_APPLIED, stats)
        _append_supplier_file_log(supplier_file, message)
        if supplier_file:
            supplier_file.status = SupplierFile.STATUS_SUCCESS
            supplier_file.save(update_fields=["status"])

        PersistentNotification.objects.create(
            user_id=user_id,
            level="success",
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
        if supplier_file:
            supplier_file.status = SupplierFile.STATUS_ERROR
            supplier_file.save(update_fields=["status"])
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
        if supplier_file:
            supplier_file.status = SupplierFile.STATUS_ERROR
            supplier_file.save(update_fields=["status"])
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
    экран сопоставления колонок и импорт. Файлы в очереди или в обработке
    тоже не трогаются.
    """
    keep_last = max(getattr(settings, "SUPPLIER_FILES_KEEP_LAST", 1), 1)
    deleted_count = 0
    in_progress = (SupplierFile.STATUS_QUEUED, SupplierFile.STATUS_RUNNING)

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
