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
    'dataframe',
    'product',
    'supplier_feed',
    'supplier'
]

PROJECT_MIDDLEWARE = [
    'core.middleware.LoginRequiredMiddleware',
    'core.middleware.toaster_middleware',
]

PIM_TOKEN = os.environ.get('PIM_TOKEN')
PIM_HOST = os.environ.get('PIM_HOST')