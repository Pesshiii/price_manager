from celery import shared_task

from core.models import PersistentNotification

from .functions import load_setting
from .models import Setting


@shared_task
def process_setting_upload(setting_id: int, user_id: int) -> dict:
    """
    Фоновая загрузка товаров поставщика по настройке.
    """
    try:
        setting = Setting.objects.get(pk=setting_id)
    except Setting.DoesNotExist:
        return {"status": "error", "message": f"Настройка #{setting_id} не найдена"}

    supplier_file = setting.supplierfiles.order_by("-pk").first()
    if supplier_file:
        supplier_file.status = 0
        supplier_file.logs = "Загрузка запущена"
        supplier_file.save(update_fields=["status", "logs"])

    try:
        products = load_setting(setting_id)
        if products is None:
            message = f"Загрузка файла через настройку «{setting.name}»: нет связок."
            status = -1
        else:
            message = (
                f"Загрузка файла через настройку «{setting.name}» завершена. "
                f"Обработано {len(products)} товаров."
            )
            status = 1

        if supplier_file:
            supplier_file.status = status
            supplier_file.logs = message
            supplier_file.save(update_fields=["status", "logs"])

        PersistentNotification.objects.create(
            user_id=user_id,
            level="success" if status == 1 else "warning",
            message=message,
        )
        return {"status": "ok", "message": message}
    except Exception as exc:
        error_message = f"Ошибка фоновой загрузки настройки «{setting.name}»: {exc}"
        if supplier_file:
            supplier_file.status = -1
            supplier_file.logs = error_message
            supplier_file.save(update_fields=["status", "logs"])
        PersistentNotification.objects.create(
            user_id=user_id,
            level="danger",
            message=error_message,
        )
        raise
