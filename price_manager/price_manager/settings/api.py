import os
# /api/ paths that anonymous users may hit (CSRF bootstrap + login)
LOGIN_EXEMPT_API_PREFIXES = (
    '/api/auth/csrf/',
    '/api/auth/login/',
)

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:5173,http://localhost:5174',
    ).split(',')
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = True