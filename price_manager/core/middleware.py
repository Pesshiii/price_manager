from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, resolve_url
from django.urls import NoReverseMatch, reverse
from django.http import HttpResponse, JsonResponse
from django_htmx.http import HttpResponseClientRedirect, reswap, trigger_client_event
from django.contrib import messages


class Bitrix24LinkRequiredMiddleware:
    """Send a logged-in user with no linked Bitrix24 account to link one.

    Runs after LoginRequiredMiddleware, so anonymous users never get here.
    Inert unless BITRIX24_LINK_REQUIRED is on and the Bitrix24 login is
    configured, which keeps every other test suite and a Bitrix24 outage from
    locking anyone out. Superusers are exempt so there is always a way into
    the admin.
    """

    EXEMPT_URL_NAMES = (
        'bitrix24-link', 'bitrix24-login', 'bitrix24-callback',
        'login', 'logout', 'toast-messages',
    )
    EXEMPT_PREFIXES = ('/admin/', '/api/')

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_paths = {reverse(name) for name in self.EXEMPT_URL_NAMES}
        self.exempt_prefixes = self.EXEMPT_PREFIXES + tuple(
            prefix for prefix in (settings.STATIC_URL, settings.MEDIA_URL) if prefix
        )

    def __call__(self, request):
        if self._must_link(request):
            target = reverse('bitrix24-link')
            next_url = self._next_url(request)
            if next_url:
                target += '?' + urlencode({'next': next_url})
            if request.headers.get('HX-Request'):
                # A 302 would be followed by htmx and swapped into the fragment.
                return HttpResponseClientRedirect(target)
            return redirect(target)
        return self.get_response(request)

    def _must_link(self, request) -> bool:
        from core import bitrix24
        from core.models import Bitrix24Account

        if not settings.BITRIX24_LINK_REQUIRED or not bitrix24.is_configured():
            return False
        user = request.user
        if not user.is_authenticated or user.is_superuser:
            return False
        path = request.path_info
        if path in self.exempt_paths or path.startswith(self.exempt_prefixes):
            return False
        return not Bitrix24Account.objects.filter(user=user).exists()

    def _next_url(self, request) -> str:
        # For htmx the request is a fragment; come back to the page it was on.
        if request.headers.get('HX-Request'):
            current = urlparse(request.headers.get('HX-Current-URL', ''))
            return current.path + (f'?{current.query}' if current.query else '')
        if request.method == 'GET':
            return request.get_full_path()
        return ''



class LoginRequiredMiddleware:
    """Redirect anonymous users to the login page for protected views."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_path = self._resolve_to_path(settings.LOGIN_URL)
        self.exempt_paths = {self.login_path}

        for url in getattr(settings, "LOGIN_EXEMPT_URLS", ()):
            resolved_path = self._resolve_to_path(url)
            if resolved_path:
                self.exempt_paths.add(resolved_path)

        self.static_prefixes = tuple(
            self._normalize_prefix(prefix)
            for prefix in (getattr(settings, "STATIC_URL", None), getattr(settings, "MEDIA_URL", None))
            if prefix
        )

        self.api_exempt_prefixes = tuple(
            getattr(settings, "LOGIN_EXEMPT_API_PREFIXES", ())
        )

    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)

        path = request.path_info

        if self._is_exempt(path):
            return self.get_response(request)

        if path.startswith("/api/"):
            return JsonResponse({"detail": "Authentication required."}, status=401)

        return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

    def _is_exempt(self, path: str) -> bool:
        if not path:
            return False

        if any(path.startswith(prefix) for prefix in self.static_prefixes):
            return True

        if path in self.exempt_paths:
            return True

        # Allow access to the admin authentication views so the default admin login works.
        if path.startswith("/admin/login") or path.startswith("/admin/logout"):
            return True

        if any(path.startswith(prefix) for prefix in self.api_exempt_prefixes):
            return True

        return False

    def _resolve_to_path(self, url: str | None) -> str | None:
        if not url:
            return None

        try:
            resolved = resolve_url(url)
        except NoReverseMatch:
            resolved = url

        parsed = urlparse(str(resolved))
        return parsed.path or "/"

    def _normalize_prefix(self, prefix: str) -> str:
        parsed = urlparse(prefix)
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        return path



def toaster_middleware(get_response):
    """
    Solution for dynamic toasters in django by:
        Josh Karamuth(https://github.com/confuzeus)
    For more information check out his blog:
        https://joshkaramuth.com/blog/django-messages-toast-htmx/
    """
    def middleware(request):
        response = get_response(request)

        storage = messages.get_messages(request)
        if len(storage) > 0:
            response = trigger_client_event(response, "toasts:fetch", after="settle")

        return response

    return middleware
