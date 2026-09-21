import os

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


# LOGIN WITH BITRIX24 (core/bitrix24.py)
#
# A local app registered on the portal. The button on the login page appears
# only when all three are set; empty values just switch the feature off.
BITRIX24_PORTAL = os.environ.get('BITRIX24_PORTAL', '')  # host only, e.g. company.bitrix24.kz
BITRIX24_CLIENT_ID = os.environ.get('BITRIX24_CLIENT_ID', '')
BITRIX24_CLIENT_SECRET = os.environ.get('BITRIX24_CLIENT_SECRET', '')
# Differs from the default only for an isolated on-premise Bitrix24.
BITRIX24_OAUTH_SERVER = os.environ.get('BITRIX24_OAUTH_SERVER', 'https://oauth.bitrix.info')
# Policy, expected to change: while PM is young every active Bitrix24 employee
# may log in and gets a PM user on first login. false = only people who
# already have a PM user (matched by e-mail) get in.
BITRIX24_AUTO_CREATE_USERS = os.environ.get('BITRIX24_AUTO_CREATE_USERS', 'true').lower() == 'true'

