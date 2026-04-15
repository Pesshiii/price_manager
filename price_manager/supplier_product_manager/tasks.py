from celery import shared_task
from django.utils import timezone

from core.models import PersistentNotification

from .functions import load_setting
from .models import Setting, SupplierFile


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
