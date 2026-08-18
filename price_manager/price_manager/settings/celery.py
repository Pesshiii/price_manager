from .base import TIME_ZONE
import os
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

SUPPLIER_FILES_KEEP_LAST = int(os.environ.get('SUPPLIER_FILES_KEEP_LAST', 0))


CELERY_BEAT_SCHEDULE = {
    'update-prices': {
        'task': 'main_product_manager.update_prices',
        'schedule': CELERY_PRICE_UPDATE_MINUTES * 60,
    },
    'update-stocks': {
        'task': 'main_product_manager.update_stocks',
        'schedule': CELERY_STOCK_UPDATE_MINUTES * 60,
    },
    'update-logs': {
        'task': 'main_product_manager.update_logs',
        'schedule': CELERY_LOG_UPDATE_MINUTES * 60,
    },
    'update-logs': {
            'task': 'main_product_manager.delete_outdated_logs',
            'schedule': 60,
        },
    'cleanup-supplier-files': {
        'task': 'supplier_product_manager.cleanup_supplier_files_task',
        'schedule': CELERY_SUPPLIER_FILES_CLEANUP_MINUTES * 60,
    },
    'create-pim-links':{
        'task': 'main_product_manager.create_pim_links',
        'schedule': 1800,
    }
}