from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import resolve_url
from django.urls import NoReverseMatch


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

    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)

        path = request.path_info

        if self._is_exempt(path):
            return self.get_response(request)

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
