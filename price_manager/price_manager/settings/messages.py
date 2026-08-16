
# Message System
from django.contrib import messages 

MESSAGE_TAGS = {
    messages.DEBUG: 'debug',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'mainproducts'
LOGOUT_REDIRECT_URL = 'login'
LOGIN_EXEMPT_URLS = (
    'login',
    'logout',
    'admin:login',
    'admin:logout',
    'admin:password_reset',
    'admin:password_reset_done',
    'admin:password_reset_confirm',
    'admin:password_reset_complete',
)