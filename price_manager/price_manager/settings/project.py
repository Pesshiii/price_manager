import os

PROJECT_INSTALLED_APPS = [    
    'api_auth',
    'core',
    'file_manager',
    'supplier_product_manager',
    'product_price_manager',
    'main_product_manager',
    'supplier_manager',
    'blogapp',
    'developers',
    'dataframe',
    'product',
    'supplier_feed',
    'supplier',
    'pricing',
]

PROJECT_MIDDLEWARE = [
    'core.middleware.LoginRequiredMiddleware',
    'core.middleware.Bitrix24LinkRequiredMiddleware',
    'core.middleware.toaster_middleware',
]

PIM_TOKEN = os.environ.get('PIM_TOKEN')
PIM_HOST = os.environ.get('PIM_HOST')

# Import guard (supplier_product_manager/guard.py): a price file whose price or
# stock coverage falls below RATIO x the median of the setting's last WINDOW
# applied imports waits for confirmation instead of being applied. Until a
# setting has MIN_HISTORY applied imports, every import waits for confirmation.
# 0.7 was calibrated on production history: ordinary imports stay within a few
# percent of the median, genuine catalogue changes within ~15%, broken files
# drop by an order of magnitude.
SUPPLIER_IMPORT_GUARD_RATIO = float(os.environ.get('SUPPLIER_IMPORT_GUARD_RATIO', 0.7))
SUPPLIER_IMPORT_GUARD_WINDOW = int(os.environ.get('SUPPLIER_IMPORT_GUARD_WINDOW', 5))
SUPPLIER_IMPORT_GUARD_MIN_HISTORY = int(os.environ.get('SUPPLIER_IMPORT_GUARD_MIN_HISTORY', 3))
