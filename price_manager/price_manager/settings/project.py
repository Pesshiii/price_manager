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
    'supplier',
    'pricing',
]

PROJECT_MIDDLEWARE = [
    'core.middleware.LoginRequiredMiddleware',
    'core.middleware.toaster_middleware',
]

PIM_TOKEN = os.environ.get('PIM_TOKEN')
PIM_HOST = os.environ.get('PIM_HOST')

# Выше скольких строк таблица главной перестаёт группироваться по pim_id.
#
# Оконные функции в main_product_manager.grouping считаются по всей партиции,
# поэтому стоимость растёт линейно с размером таблицы (~20 мкс на строку) — на
# некатегоризованной корзине прода в 156 тыс. строк это 3 с на страницу против
# 78 мс без группировки, при том что заголовок группы рисуется лишь на 6,9 %
# страниц. Выше порога таблица отдаётся плоской, как до #155.
#
# 5000 подобрано по замерам (#163): накладные расходы группировки на такой
# таблице ~57 мс, и все реальные категории (крупнейшая — 67 товаров) остаются
# сгруппированными с огромным запасом.
MAINPRODUCT_GROUPING_ROW_LIMIT = int(os.environ.get('MAINPRODUCT_GROUPING_ROW_LIMIT', 5000))