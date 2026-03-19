from celery import shared_task

from .functions import load_setting


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def load_setting_task(self, setting_id: int) -> dict:
    products = load_setting(setting_id)
    processed = len(products) if products is not None else 0
    return {'setting_id': setting_id, 'processed': processed}
