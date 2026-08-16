THIRD_PARTY_INSTALLED_APPS = [
    'django_tables2',
    'import_export',
    'django_filters',
    'dal',
    'dal_select2',
    'django_htmx',
    'template_partials',
    'widget_tweaks',
    'crispy_bootstrap4',
    'crispy_forms',
    'mptt',
    'storages',
    'rest_framework',
    'corsheaders',
]

THIRD_PARTY_MIDDLEWARE = [
    'django_htmx.middleware.HtmxMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
]


# TAGS FOR CRISPY FORMS

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap4'
CRISPY_TEMPLATE_PACK = 'bootstrap4'

