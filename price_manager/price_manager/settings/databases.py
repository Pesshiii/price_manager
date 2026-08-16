import os
# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB','price_manager'),
        'USER': os.environ.get('POSTGRES_USER','priceuser'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD','postgres'),
        'HOST': os.environ.get('DB_HOST','localhost'),
        'PORT': os.environ.get('DB_PORT','5432'),
    }
}
DATA_UPLOAD_MAX_NUMBER_FIELDS = 50000


REDIS_URL = os.environ.get('REDIS_URL', None)
if not REDIS_URL is None:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                "PICKLE_VERSION": -1,  # Use highest protocol for efficiency
                "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",  # Optional compression
            },
            'KEY_PREFIX': 'price_manager',
            'TIMEOUT': None,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
        }
    }
