from celery import shared_task
from django.http import QueryDict
from django.utils import timezone
from django.conf import settings

from core.models import PersistentNotification
from main_product_manager.utils import recalculate_search_vectors, compute_supplier_sku
from main_product_manager.models import MainProduct

from .functions import load_setting, SupplierFileStorageMissingError
from .filters import SupplierProductFilter
from .models import (
    CopySupplierProductsToMainRun,
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

    try:
        _append_supplier_file_log(supplier_file, "Чтение и обработка файла")
        products = load_setting(setting_id)
        duration_seconds = round((timezone.now() - started_at).total_seconds(), 2)

        processed_rows = len(products) if products else 0
        errors_count = 0 if products else 1
        success = products is not None

        if success:
            message = (
                f"Импорт «{setting.name}» завершен: обработано строк {processed_rows}, "
                f"ошибок {errors_count}, длительность {duration_seconds} сек."
            )
            status = SupplierFile.STATUS_SUCCESS
            level = "success"
        else:
            message = (
                f"Импорт «{setting.name}» завершен с ошибкой: обработано строк {processed_rows}, "
                f"ошибок {errors_count}, длительность {duration_seconds} сек."
            )
            status = SupplierFile.STATUS_ERROR
            level = "warning"

        _append_supplier_file_log(supplier_file, message)
        if supplier_file:
            supplier_file.status = status
            supplier_file.save(update_fields=["status"])

        PersistentNotification.objects.create(
            user_id=user_id,
            level=level,
            message=message,
        )
        return {
            "status": "ok" if success else "error",
            "processed_rows": processed_rows,
            "errors": errors_count,
            "duration_seconds": duration_seconds,
            "message": message,
        }
    except SupplierFileStorageMissingError as exc:
        duration_seconds = round((timezone.now() - started_at).total_seconds(), 2)
        error_message = (
            f"Импорт «{setting.name}» завершен с ошибкой: обработано строк 0, ошибок 1, "
            f"длительность {duration_seconds} сек. Причина: Файл настройки отсутствует в media-хранилище."
        )
        _append_supplier_file_log(supplier_file, f"{error_message} ({exc})")
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
    """
    keep_last = max(getattr(settings, "SUPPLIER_FILES_KEEP_LAST", 1), 0)
    deleted_count = 0

    for setting in Setting.objects.only("id").iterator():
        file_ids = list(
            setting.supplierfiles.order_by("-pk").values_list("pk", flat=True)
        )
        ids_to_delete = file_ids[keep_last:]
        if not ids_to_delete:
            continue

        for supplier_file in SupplierFile.objects.filter(pk__in=ids_to_delete).iterator():
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
            .qs.select_related("main_product", "supplier", "manufacturer", "category")
            .filter(supplier_id=supplier_id)
            .order_by("pk")
        )

        created_count = products_qs.filter(main_product__isnull=True).count()
        processed_count = 0
        updated_links_count = 0
        touched_main_product_ids = set()
        supplier = Supplier.objects.get(id=supplier_id)
        through = MainProduct.categories.through

        for batch in _chunked(products_qs.iterator(chunk_size=batch_size), batch_size):
            processed_count += len(batch)
            if not batch:
                continue

            linked = [sp for sp in batch if sp.main_product_id]
            unlinked = [sp for sp in batch if not sp.main_product_id]
            category_links = []

            if linked:
                mps_to_update = [
                    MainProduct(id=sp.main_product_id, manufacturer=sp.manufacturer, description=sp.description)
                    for sp in linked
                ]
                MainProduct.objects.bulk_update(
                    mps_to_update, fields=["manufacturer", "description"], batch_size=batch_size
                )
                for sp in linked:
                    touched_main_product_ids.add(sp.main_product_id)
                    if sp.category_id:
                        category_links.append(through(mainproduct_id=sp.main_product_id, category_id=sp.category_id))

            if unlinked:
                new_mps = [
                    MainProduct(
                        supplier_id=supplier_id,
                        article=sp.article,
                        sku=compute_supplier_sku(sp.article, supplier),
                        name=sp.name,
                        description=sp.description,
                        manufacturer=sp.manufacturer,
                    )
                    for sp in unlinked
                ]
                MainProduct.objects.bulk_create(new_mps, batch_size=batch_size)

                for sp, mp in zip(unlinked, new_mps):
                    sp.main_product_id = mp.id
                    touched_main_product_ids.add(mp.id)
                    if sp.category_id:
                        category_links.append(through(mainproduct_id=mp.id, category_id=sp.category_id))

                SupplierProduct.objects.bulk_update(unlinked, fields=["main_product"], batch_size=batch_size)
                updated_links_count += len(unlinked)

            if category_links:
                through.objects.bulk_create(category_links, ignore_conflicts=True, batch_size=batch_size)

        for ids_chunk in _chunked(list(touched_main_product_ids), batch_size):
            recalculate_search_vectors(MainProduct.objects.filter(pk__in=ids_chunk))

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
