from .base import TIME_ZONE
import os
from celery.schedules import crontab
from price_manager.celery import app
from .databases import REDIS_URL

# Celery Configuration Options
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_URL or 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'


CELERY_PRICE_UPDATE_MINUTES = int(os.environ.get('CELERY_PRICE_UPDATE_MINUTES', 30))
CELERY_STOCK_UPDATE_MINUTES = int(os.environ.get('CELERY_STOCK_UPDATE_MINUTES', 15))
CELERY_LOG_UPDATE_MINUTES = int(os.environ.get('CELERY_LOG_UPDATE_MINUTES', 60))
CELERY_SUPPLIER_FILES_CLEANUP_MINUTES = int(os.environ.get('CELERY_SUPPLIER_FILES_CLEANUP_MINUTES', 30))
CELERY_NOTIFICATION_CLEANUP_MINUTES = int(os.environ.get('CELERY_NOTIFICATION_CLEANUP_MINUTES', 60))

# At least 1: a setting's latest file is what its mapping screen and its import
# read, so the cleanup never removes it whatever this is set to.
SUPPLIER_FILES_KEEP_LAST = int(os.environ.get('SUPPLIER_FILES_KEEP_LAST', 1))
PERSISTENT_NOTIFICATION_TTL_HOURS = int(os.environ.get('PERSISTENT_NOTIFICATION_TTL_HOURS', 72))


# Tasks that spend minutes on PIM HTTP calls and sleeps, or fan out batches
# that do, run on their own queue and worker (`celery_worker_pim` in
# docker-compose.yml). On the default queue a sync's batches took every worker
# slot, and imports, exports and update_prices waited until the sync was done.
# A task left off this list stays on the default queue `celery` — so a long
# PIM-bound task added later belongs here, and a misspelt name silently routes
# nothing (core.tests.CeleryTaskRoutesTests checks every name is a registered task).
PIM_QUEUE = 'pim'
CELERY_TASK_ROUTES = {
    name: {'queue': PIM_QUEUE}
    for name in (
        'product.backfill_products_from_pim',
        'product.refresh_products_from_pim',
        'product.sync_products_batch',
        'product.sync_product_from_pim',
        'product.sync_product_sets',
        'main_product_manager.reindex_pim_ids',
        'main_product_manager.reindex_pim_ids_batch',
    )
}


_DAY = 24 * 60 * 60  # not a setting: the leading _ keeps it out of prod's import *

# Every entry expires by its next firing (`options.expires`, seconds). While the
# worker is busy beat keeps sending, and without it the queue fills with stale
# copies — delete-outdated-logs alone adds one a minute — which then all run
# back to back once the worker frees up. With it at most one copy of each
# periodic task is ever waiting; an expired one is discarded, not run.
CELERY_BEAT_SCHEDULE = {
    'update-prices': {
        'task': 'main_product_manager.update_prices',
        'schedule': CELERY_PRICE_UPDATE_MINUTES * 60,
        'options': {'expires': CELERY_PRICE_UPDATE_MINUTES * 60},
    },
    'update-stocks': {
        'task': 'main_product_manager.update_stocks',
        'schedule': CELERY_STOCK_UPDATE_MINUTES * 60,
        'options': {'expires': CELERY_STOCK_UPDATE_MINUTES * 60},
    },
    'update-logs': {
        'task': 'main_product_manager.update_logs',
        'schedule': CELERY_LOG_UPDATE_MINUTES * 60,
        'options': {'expires': CELERY_LOG_UPDATE_MINUTES * 60},
    },
    'delete-outdated-logs': {
        'task': 'main_product_manager.delete_outdated_logs',
        'schedule': 60,
        'options': {'expires': 60},
    },
    'cleanup-supplier-files': {
        'task': 'supplier_product_manager.cleanup_supplier_files_task',
        'schedule': CELERY_SUPPLIER_FILES_CLEANUP_MINUTES * 60,
        'options': {'expires': CELERY_SUPPLIER_FILES_CLEANUP_MINUTES * 60},
    },
    'reindex-pim-ids': {
        'task': 'main_product_manager.reindex_pim_ids',
        'schedule': crontab(hour=3, minute=0),
        'options': {'expires': _DAY},
    },
    'sync-product-sets': {
        'task': 'product.sync_product_sets',
        'schedule': crontab(hour=4, minute=0),
        'options': {'expires': _DAY},
    },
    # После reindex_pim_ids: заведённые им этой ночью PMP с productId
    # получают контент в тот же прогон.
    'refresh-products-from-pim': {
        'task': 'product.refresh_products_from_pim',
        'schedule': crontab(hour=5, minute=0),
        'options': {'expires': _DAY},
    },
    'cleanup-persistent-notifications': {
        'task': 'core.cleanup_persistent_notifications',
        'schedule': CELERY_NOTIFICATION_CLEANUP_MINUTES * 60,
        'options': {'expires': CELERY_NOTIFICATION_CLEANUP_MINUTES * 60},
    },
}